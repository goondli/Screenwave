"""The Logicloom marquee scene: waves of text, each carrying one animation,
travelling across every monitor.

A wave starts just off the first screen, crosses the whole layout at
`speed`, and retires once it (and its animation's REACH) has left the last
screen. The next wave follows `wave_gap` seconds behind.
"""
import importlib.util
import math
import random
import sys
import traceback
from pathlib import Path

from kit import Pen, Wave, DEFAULT_REACH, gpoint, grect, rgba, text_layout
from gi.repository import Pango

ANIMATIONS_DIR = Path(__file__).with_name("animations")
FADE_IN = 1.5
FADE_OUT = 3.0


def log(msg):
    print(f"logicloom-saver: {msg}", file=sys.stderr, flush=True)


# -- animation plug-ins --------------------------------------------------------
class Animation:
    def __init__(self, key, module):
        self.key = key
        self.module = module
        self.name = getattr(module, "NAME", key)
        self.description = getattr(module, "DESCRIPTION", "")
        self.reach = float(getattr(module, "REACH", DEFAULT_REACH))
        self.broken = None  # error text once it has failed

    def _guard(self, what, fn, *args):
        if self.broken:
            return
        try:
            fn(*args)
        except Exception:
            self.broken = traceback.format_exc(limit=3)
            log(f"animation {self.key!r} failed in {what}() and is switched off "
                f"until the next start:\n{self.broken}")

    def setup(self, wave):
        fn = getattr(self.module, "setup", None)
        if fn:
            self._guard("setup", fn, wave)

    def draw(self, pen, wave):
        self._guard("draw", self.module.draw, pen, wave)


def discover(directory=ANIMATIONS_DIR):
    """{key: Animation} for every animations/*.py not starting with _.
    A file that fails to import is reported and left out."""
    found = {}
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        key = path.stem
        try:
            spec = importlib.util.spec_from_file_location(f"logicloom_anim_{key}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not callable(getattr(module, "draw", None)):
                raise AttributeError("it has no draw(pen, wave) function")
            found[key] = Animation(key, module)
        except Exception as e:
            log(f"animation {path.name} not loaded: {e}")
    return found


# -- the scene -------------------------------------------------------------------
class Marquee:
    def __init__(self, world, settings, animations=None, only=None, seed=None, quiet=False):
        self.world = world
        self.s = settings
        self.rng = random.Random(seed)
        self.seed_base = self.rng.randrange(1 << 30)
        all_anims = discover() if animations is None else animations
        keys = [only] if only else [k for k in settings.enabled if k in all_anims]
        missing = [k for k in ([only] if only else settings.enabled) if k not in all_anims]
        for k in missing if not quiet else ():
            log(f"animation {k!r} is enabled but there is no animations/{k}.py")
        self.anims = [all_anims[k] for k in keys]
        self.waves = []  # [(Wave, Animation or None, born)]
        self.count = 0
        self.next_spawn = 0.0
        self.t = None
        self.t0 = None
        self.dir = 1 if settings.direction == "left_to_right" else -1
        self.font = settings.font
        self.size = float(settings.text_size)
        self.glow_blur = max(4.0, self.size * 0.09)

    # -- time ---------------------------------------------------------------
    def age(self):
        return 0.0 if self.t is None else self.t - self.t0

    @property
    def run_seconds(self):
        return self.s.run_minutes * 60

    @property
    def dark(self):
        """True once run_minutes have passed and the fade to black is done."""
        return self.run_seconds > 0 and self.age() > self.run_seconds + FADE_OUT

    def advance_to(self, t):
        if self.t is None:
            self.t = self.t0 = t
        if t < self.t:
            return
        self.t = t
        if self.age() >= self.next_spawn:
            self._spawn()
        alive = []
        for wave, anim, born in self.waves:
            self._place(wave, born)
            gone = (wave.x - wave.reach > self.world.x1) if self.dir > 0 \
                else (wave.x + wave.w + wave.reach < self.world.x0)
            if not gone:
                alive.append((wave, anim, born))
        self.waves = alive

    def _spawn(self):
        i = self.count
        self.count += 1
        lines = self.s.lines or ["LOGICLOOM LLP"]
        text = lines[i % len(lines)]
        anim = None
        if self.anims:
            anim = self.rng.choice(self.anims) if self.s.order == "random" \
                else self.anims[i % len(self.anims)]
        wave = Wave(i, text, self.world, self.s.colors, float(self.s.speed), self.dir,
                    seed=self.seed_base + i)
        wave.w, wave.h = self.text_size(text)
        wave.reach = anim.reach if anim else DEFAULT_REACH
        band_h = self.world.band_bottom - self.world.band_top
        free = max(0.0, band_h - wave.h)
        wave.y = self.world.band_top + wave.h / 2 + free * self.s.lane / 100
        born = self.age()
        self._place(wave, born)
        if anim:
            anim.setup(wave)
        self.waves.append((wave, anim, born))
        # the next wave enters once this one, reach included, is fully in
        # and wave_gap seconds have passed
        self.next_spawn = born + (wave.w + 2 * wave.reach) / wave.speed + self.s.wave_gap

    def _place(self, wave, born):
        wave.t = self.age() - born
        travelled = wave.speed * wave.t
        if self.dir > 0:
            wave.x = self.world.x0 - wave.reach - wave.w + travelled
        else:
            wave.x = self.world.x1 + wave.reach - travelled

    def text_size(self, text):
        ext = text_layout(text, self.size, self.font).get_pixel_extents()[1]
        return float(ext.width), float(ext.height)

    # -- drawing --------------------------------------------------------------
    def draw(self, snap, view):
        """Draw what `view` (a kit.Screen) shows, on a snapshot whose origin
        is that screen's top-left corner."""
        snap.append_color(rgba(self.s.background), grect(0, 0, view.w, view.h))
        if self.dark:
            return
        snap.save()
        snap.translate(gpoint(-view.x, -view.y))
        pen = Pen(snap, view, self.world)
        for wave, anim, _born in self.waves:
            if anim:
                anim.draw(pen, wave)
        for wave, _anim, _born in self.waves:
            self._draw_text(pen, wave)
        snap.restore()

        cover = 0.0
        if self.age() < FADE_IN:
            cover = 1 - self.age() / FADE_IN
        if self.run_seconds > 0 and self.age() > self.run_seconds:
            cover = max(cover, min(1.0, (self.age() - self.run_seconds) / FADE_OUT))
        if cover > 0:
            snap.append_color(rgba(self.s.background, cover), grect(0, 0, view.w, view.h))

    def _draw_text(self, pen, wave):
        if not pen.visible(wave.x - self.size, wave.y - wave.h, wave.x + wave.w + self.size,
                           wave.y + wave.h):
            return
        lay = text_layout(wave.text, self.size, self.font)
        top = wave.y - wave.h / 2
        amp = float(self.s.wave_height)
        snap = pen.snap
        if amp <= 0:
            for color, blur in ((self.s.glow_color, self.glow_blur), (self.s.text_color, 0)):
                if blur:
                    snap.push_blur(blur)
                snap.save()
                snap.translate(gpoint(wave.x, top))
                snap.append_layout(lay, rgba(color))
                snap.restore()
                if blur:
                    snap.pop()
            return

        # Rippling letters: each character drawn on its own, lifted by a
        # sine wave that rolls along the layout in the travel direction.
        glyphs = self._glyphs(wave.text, lay)
        wavelength = max(200.0, self.size * 4.5)
        phase = wave.t * 3.2 * self.dir
        placed = []
        for gx, glay, gw in glyphs:
            x = wave.x + gx
            if not pen.visible(x - 40, top - amp - 40, x + gw + 40, top + wave.h + amp + 40):
                continue
            dy = amp * math.sin(2 * math.pi * x / wavelength - phase)
            placed.append((x, top + dy, glay))
        if not placed:
            return
        snap.push_blur(self.glow_blur)
        for x, y, glay in placed:
            snap.save()
            snap.translate(gpoint(x, y))
            snap.append_layout(glay, rgba(self.s.glow_color))
            snap.restore()
        snap.pop()
        for x, y, glay in placed:
            snap.save()
            snap.translate(gpoint(x, y))
            snap.append_layout(glay, rgba(self.s.text_color))
            snap.restore()

    def _glyphs(self, text, lay):
        """[(x offset, layout, width)] per non-space character, positioned as
        Pango laid out the whole line (keeps kerning). Cached per text."""
        cache = self.__dict__.setdefault("_glyph_cache", {})
        hit = cache.get(text)
        if hit is not None:
            return hit
        out = []
        byte = 0
        for ch in text:
            nbytes = len(ch.encode("utf-8"))
            if not ch.isspace():
                pos = lay.index_to_pos(byte)
                glay = text_layout(ch, self.size, self.font)
                out.append((pos.x / Pango.SCALE, glay, pos.width / Pango.SCALE))
            byte += nbytes
        cache[text] = out
        return out
