"""Drawing kit for Logicloom Screensaver animations.

An animation is one .py file in the animations/ folder:

    NAME = "Neural network"        # shown in the settings window
    DESCRIPTION = "..."            # optional, one line
    REACH = 600                    # optional: px it draws beyond the text,
                                   # each side (default 500)

    def setup(wave):               # optional: once, when the wave starts
        wave.data.nodes = [...]    # pick random layout here, with wave.rng

    def draw(pen, wave):           # every frame, once per screen
        pen.circle(wave.cx, wave.y, 40, wave.color(0))

Coordinates are GNOME layout pixels across ALL monitors (see pen.world), so
a shape at x=2000 shows on whichever screen covers x=2000.

Rules that keep the three screens in step:
  - draw() must depend only on wave.t and what setup() stored. Each screen
    calls it separately for the same moment, so never use random numbers
    or change wave.data inside draw().
  - keep draw() cheap: about 1 ms per call. `python3 saver.py --profile
    --only NAME` measures it.

Files starting with _ are not loaded (_template.py is the starting point).
"""
import math
import random
from types import SimpleNamespace

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Graphene, Gsk, Pango, PangoCairo  # noqa: E402

DEFAULT_REACH = 500


# -- colours -------------------------------------------------------------------
def to_rgb(color):
    """'#4dd9ff' or (r, g, b) in 0..1 -> (r, g, b)."""
    if isinstance(color, str):
        h = color.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return tuple(color)


_rgba_cache = {}


def rgba(color, alpha=1.0):
    key = (color if isinstance(color, str) else tuple(color), round(alpha, 3))
    c = _rgba_cache.get(key)
    if c is None:
        if len(_rgba_cache) > 8192:
            _rgba_cache.clear()
        c = Gdk.RGBA()
        c.red, c.green, c.blue = to_rgb(color)
        c.alpha = max(0.0, min(1.0, alpha))
        _rgba_cache[key] = c
    return c


def mix(a, b, k):
    """Blend two colours: k=0 gives a, k=1 gives b."""
    a, b = to_rgb(a), to_rgb(b)
    return tuple(x + (y - x) * k for x, y in zip(a, b))


def stops(*pairs):
    out = []
    for offset, color in pairs:
        s = Gsk.ColorStop()
        s.offset, s.color = offset, color
        out.append(s)
    return out


def grect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


def gpoint(x, y):
    return Graphene.Point().init(x, y)


# -- easing helpers for animations -------------------------------------------
def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def smooth(k):
    """0..1 -> 0..1 with gentle start and end."""
    k = clamp(k)
    return k * k * (3 - 2 * k)


def pulse(t, period, width=0.25):
    """1 near the start of every `period` seconds, fading to 0 by `width`."""
    phase = (t % period) / period
    return clamp(1 - phase / width) if width > 0 else 0.0


# -- layout of the monitors ---------------------------------------------------
class Screen:
    def __init__(self, x, y, w, h, name=""):
        self.x, self.y, self.w, self.h, self.name = x, y, w, h, name

    @property
    def x1(self):
        return self.x + self.w

    @property
    def y1(self):
        return self.y + self.h

    def contains(self, px, py):
        return self.x <= px <= self.x1 and self.y <= py <= self.y1

    def __repr__(self):
        return f"{self.name}@{self.x},{self.y} {self.w}x{self.h}"


class World:
    """All monitors in GNOME's layout.

    x0..x1, y0..y1   bounding box of every screen
    band_top/bottom  the height range every screen shares; a line drawn in
                     it crosses all of them (falls back to y0..y1)
    screens          left to right
    """

    def __init__(self, screens):
        self.screens = sorted(screens, key=lambda s: (s.x, s.y))
        self.x0 = min(s.x for s in screens)
        self.y0 = min(s.y for s in screens)
        self.x1 = max(s.x1 for s in screens)
        self.y1 = max(s.y1 for s in screens)
        top = max(s.y for s in screens)
        bottom = min(s.y1 for s in screens)
        if bottom - top < 100:
            top, bottom = self.y0, self.y1
        self.band_top, self.band_bottom = top, bottom

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0

    def screen_at(self, x, y=None):
        for s in self.screens:
            if s.x <= x <= s.x1 and (y is None or s.y <= y <= s.y1):
                return s
        return min(self.screens, key=lambda s: abs((s.x + s.x1) / 2 - x))


# -- a wave: one line of text plus one animation crossing the screens ---------
class Wave:
    """What an animation gets. Read-only except wave.data in setup().

    t           seconds since this wave started
    x, w        left edge and width of the text (layout pixels)
    cx          centre x of the text
    y, h        centre y and height of the text
    text        the line being shown
    dir         +1 moving right, -1 moving left
    speed       px per second
    index       0, 1, 2 ... counts waves since the screensaver started
    world       the monitors (World)
    data        your own storage, filled in setup()
    rng         random.Random for setup() only
    color(i)    i-th colour from the settings (wraps around)
    ahead(d)    x that is d px in front of the text in the travel direction
    behind(d)   x that is d px behind the text
    """

    def __init__(self, index, text, world, colors, speed, direction, seed):
        self.index = index
        self.text = text
        self.world = world
        self._colors = [to_rgb(c) for c in colors] or [(1, 1, 1)]
        self.speed = speed
        self.dir = direction
        self.rng = random.Random(seed)
        self.data = SimpleNamespace()
        self.t = 0.0
        self.x = self.w = self.y = self.h = 0.0
        self.reach = DEFAULT_REACH

    @property
    def cx(self):
        return self.x + self.w / 2

    def color(self, i=0):
        return self._colors[i % len(self._colors)]

    def ahead(self, d):
        return self.x + self.w + d if self.dir > 0 else self.x - d

    def behind(self, d):
        return self.x - d if self.dir > 0 else self.x + self.w + d


# -- the pen ---------------------------------------------------------------------
_layouts = {}
_pango_ctx = None


def pango_context():
    global _pango_ctx
    if _pango_ctx is None:
        _pango_ctx = PangoCairo.FontMap.get_default().create_context()
    return _pango_ctx


def text_layout(text, size, font="Ubuntu Bold"):
    """A cached Pango layout of `text` at `size` px height."""
    key = (text, round(size, 1), font)
    lay = _layouts.get(key)
    if lay is None:
        if len(_layouts) > 4096:
            _layouts.clear()
        lay = Pango.Layout.new(pango_context())
        fd = Pango.FontDescription.from_string(font)
        fd.set_absolute_size(size * Pango.SCALE)
        lay.set_font_description(fd)
        lay.set_text(text, -1)
        _layouts[key] = lay
    return lay


# Why no Gsk paths for lines and circles: GTK's renderer rasterises every new
# path on the CPU each frame. Measured live, the neural animation took 67% of
# a core with paths. Rotated rectangles and radial gradients are drawn by the
# GPU, so line/lines/circle/ring use those; only polygon() still needs a path.
_shape_stops = {}


def _ring_stops(color, alpha, radii, outer):
    """Cached stops for a radial gradient of radius `outer` that is opaque
    between radii[1] and radii[2] and fades out over radii[0]..[1] and
    radii[2]..[3]."""
    ckey = color if isinstance(color, str) else tuple(round(c, 3) for c in color)
    key = (ckey, round(alpha, 3), tuple(round(p / outer, 3) for p in radii))
    st = _shape_stops.get(key)
    if st is None:
        if len(_shape_stops) > 4096:
            _shape_stops.clear()
        clear, solid = rgba(color, 0), rgba(color, alpha)
        offs = []
        last = 0.0
        for p in radii:  # offsets must never go backwards
            last = max(last, min(1.0, p / outer))
            offs.append(last)
        st = stops((0.0, solid if offs[0] <= 0 else clear), (offs[0], clear if offs[0] > 0 else solid),
                   (offs[1], solid), (offs[2], solid), (offs[3], clear))
        _shape_stops[key] = st
    return st


class Pen:
    """Draws on one screen, in layout coordinates. Shapes entirely off this
    screen are skipped, so drawing across the whole layout is fine."""

    def __init__(self, snap, view, world):
        self.snap = snap
        self.view = view
        self.world = world
        self._vx0, self._vy0 = view.x - 4, view.y - 4
        self._vx1, self._vy1 = view.x1 + 4, view.y1 + 4
        self._rotations = 0  # inside pen.rotated() boxes are not where they look

    @property
    def screen(self):
        """The Screen this pen draws on."""
        return self.view

    def visible(self, x0, y0, x1, y1):
        """True if the box x0..x1, y0..y1 touches this screen."""
        if self._rotations:
            return True
        return not (x1 < self._vx0 or x0 > self._vx1 or y1 < self._vy0 or y0 > self._vy1)

    # shapes
    def rect(self, x, y, w, h, color, alpha=1.0):
        if alpha > 0.002 and self.visible(x, y, x + w, y + h):
            self.snap.append_color(rgba(color, alpha), grect(x, y, w, h))

    def _radial(self, x, y, outer, st):
        self.snap.append_radial_gradient(grect(x - outer, y - outer, 2 * outer, 2 * outer),
                                         gpoint(x, y), outer, outer, 0.0, 1.0, st)

    def circle(self, x, y, r, color, alpha=1.0):
        if alpha > 0.002 and r > 0 and self.visible(x - r, y - r, x + r, y + r):
            outer = r + 0.5  # half a pixel of soft edge each side of r
            self._radial(x, y, outer, _ring_stops(color, alpha, (0, 0, r - 0.5, outer), outer))

    def ring(self, x, y, r, width, color, alpha=1.0):
        if alpha > 0.002 and r > 0 and self.visible(x - r - width, y - r - width,
                                                    x + r + width, y + r + width):
            inner, outer = max(0.0, r - width / 2), r + width / 2 + 0.5
            if width < 1:  # hairline: thinner by fading rather than by pixels
                alpha *= width
                width = 1.0
                inner = max(0.0, r - 0.5)
            radii = (max(0.0, inner - 0.5), inner + 0.5, r + width / 2 - 0.5, outer)
            self._radial(x, y, outer, _ring_stops(color, alpha, radii, outer))

    def glow(self, x, y, r, color, alpha=0.5):
        """Soft light, brightest in the middle."""
        if alpha > 0.002 and r > 0 and self.visible(x - r, y - r, x + r, y + r):
            self.snap.append_radial_gradient(
                grect(x - r, y - r, 2 * r, 2 * r), gpoint(x, y), r, r, 0.0, 1.0,
                stops((0.0, rgba(color, alpha)), (0.35, rgba(color, alpha * 0.45)),
                      (1.0, rgba(color, 0))))

    def _segment(self, x1, y1, x2, y2, width, c, ext1, ext2):
        """A rotated rectangle from (x1,y1) to (x2,y2), lengthened by ext1
        before the start and ext2 past the end."""
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-3:
            return
        snap = self.snap
        snap.save()
        snap.translate(gpoint(x1, y1))
        snap.rotate(math.degrees(math.atan2(dy, dx)))
        snap.append_color(c, grect(-ext1, -width / 2, length + ext1 + ext2, width))
        snap.restore()

    def line(self, x1, y1, x2, y2, width, color, alpha=1.0):
        if alpha > 0.002 and self.visible(min(x1, x2) - width, min(y1, y2) - width,
                                          max(x1, x2) + width, max(y1, y2) + width):
            self._segment(x1, y1, x2, y2, width, rgba(color, alpha), 0, 0)
            if alpha >= 0.99 and width >= 3:  # round ends; invisible overlap when opaque
                self.circle(x1, y1, width / 2, color)
                self.circle(x2, y2, width / 2, color)

    def lines(self, points, width, color, alpha=1.0, closed=False):
        """A connected line through [(x, y), ...]."""
        if alpha <= 0.002 or len(points) < 2:
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if not self.visible(min(xs) - width, min(ys) - width, max(xs) + width, max(ys) + width):
            return
        pts = list(points) + ([points[0]] if closed else [])
        c = rgba(color, alpha)
        # Opaque: overlap the joints by half the width so corners are filled.
        # See-through: don't, or every joint would show as a brighter dot.
        joint = width / 2 if alpha >= 0.99 else 0.0
        for i in range(len(pts) - 1):
            self._segment(*pts[i], *pts[i + 1], width, c, joint if i else 0,
                          joint if i < len(pts) - 2 else 0)
        if alpha >= 0.99 and width >= 3 and not closed:
            self.circle(*pts[0], width / 2, color)
            self.circle(*pts[-1], width / 2, color)

    def polygon(self, points, color, alpha=1.0):
        """A filled shape through [(x, y), ...]."""
        if alpha <= 0.002 or len(points) < 3:
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if not self.visible(min(xs), min(ys), max(xs), max(ys)):
            return
        b = Gsk.PathBuilder.new()
        b.move_to(*points[0])
        for p in points[1:]:
            b.line_to(*p)
        b.close()
        self.snap.append_fill(b.to_path(), Gsk.FillRule.WINDING, rgba(color, alpha))

    def text(self, x, y, text, size, color, alpha=1.0, font="Ubuntu Bold", anchor="center"):
        """Text centred on (x, y); anchor "left" puts its left edge at x."""
        if alpha <= 0.002 or not text:
            return
        lay = text_layout(text, size, font)
        ext = lay.get_pixel_extents()[1]
        left = x - ext.width / 2 if anchor == "center" else x
        top = y - ext.height / 2
        if not self.visible(left, top, left + ext.width, top + ext.height):
            return
        self.snap.save()
        self.snap.translate(gpoint(left, top))
        self.snap.append_layout(lay, rgba(color, alpha))
        self.snap.restore()

    # grouping
    def rotated(self, cx, cy, degrees):
        """with pen.rotated(x, y, 30): ... draws rotated around (x, y)."""
        return _Rotated(self, cx, cy, degrees)

    def faded(self, alpha):
        """with pen.faded(0.5): ... draws everything inside at half opacity."""
        return _Faded(self.snap, alpha)


class _Rotated:
    def __init__(self, pen, cx, cy, deg):
        self.pen, self.cx, self.cy, self.deg = pen, cx, cy, deg

    def __enter__(self):
        snap = self.pen.snap
        snap.save()
        snap.translate(gpoint(self.cx, self.cy))
        snap.rotate(self.deg)
        snap.translate(gpoint(-self.cx, -self.cy))
        self.pen._rotations += 1

    def __exit__(self, *exc):
        self.pen._rotations -= 1
        self.pen.snap.restore()


class _Faded:
    def __init__(self, snap, alpha):
        self.snap, self.alpha = snap, alpha

    def __enter__(self):
        self.snap.push_opacity(max(0.0, min(1.0, self.alpha)))

    def __exit__(self, *exc):
        self.snap.pop()


__all__ = ["Pen", "Wave", "World", "Screen", "rgba", "to_rgb", "mix", "clamp",
           "smooth", "pulse", "math", "text_layout"]
