#!/usr/bin/env python3
"""Logicloom Screensaver: the marquee across every monitor.

GNOME on Wayland will not let one window span monitors, so this opens one
fullscreen window per monitor. All of them draw the same Marquee scene, each
shifted by its monitor's place in the GNOME layout, so text leaving one
screen's edge comes in on the next. Drawing is Gtk.Snapshot (GPU).

Any key, click, scroll or mouse move quits.

  saver.py                          run until input
  saver.py --duration 10            run for 10 s
  saver.py --snapshot out.png --at 8 [--only neural]
                                    picture of the whole layout at t=8 s
  saver.py --align                  line-up pattern: arrow keys move the picture
                                    on the screen under the mouse, Enter saves
  saver.py --profile [--only neural]
                                    time the drawing, per screen per frame
"""
import argparse
import math
import os
import re
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Gdk, GLib, Gsk, Gtk  # noqa: E402

import settings as settings_mod  # noqa: E402
from kit import Pen, gpoint, grect, physical_world, rgba  # noqa: E402
from marquee import Marquee  # noqa: E402

APP_ID = "in.maridian.LogicloomSaver"
GRACE = 1.2          # ignore input this long after start (pointer settles)
MOVE_QUIT_PX = 14
SETTLE = 0.8         # ignore motion this long after a window is mapped or resized


def monitors(display):
    """[(Gdk.Monitor, (name, x, y, w, h, width_mm, height_mm, inches))]"""
    out = []
    ms = display.get_monitors()
    for i in range(ms.get_n_items()):
        m = ms.get_item(i)
        g = m.get_geometry()
        # 'Acer Technologies 27"': the name's diagonal is more exact than the
        # EDID size, which is rounded to whole cm
        found = re.search(r'(\d{2}(?:\.\d)?)"', m.get_description() or "")
        out.append((m, (m.get_connector() or f"mon{i}", g.x, g.y, g.width, g.height,
                        m.get_width_mm(), m.get_height_mm(),
                        float(found.group(1)) if found else None)))
    return out


def world_of(display, s):
    infos = [info for _m, info in monitors(display)]
    inches = {n: d for n, *_r, d in infos if d}
    inches.update(s.screen_inches)
    return physical_world([info[:7] for info in infos], s.match_sizes, s.screen_shift, inches,
                          level=s.level)


def draw_layout(snap, scene, scale, gaps=(0.16, 0.16, 0.18)):
    """The whole layout scaled into one picture (preview and --snapshot)."""
    w = scene.world
    snap.save()
    snap.scale(scale, scale)
    snap.append_color(rgba(gaps), grect(0, 0, w.w, w.h))
    for s in w.screens:
        snap.save()
        snap.translate(gpoint(s.x - w.x0, s.y - w.y0))
        snap.push_clip(grect(0, 0, s.w, s.h))
        snap.scale(1 / s.scale, 1 / s.scale)  # scene.draw works in monitor pixels
        scene.draw(snap, s)
        snap.pop()
        snap.restore()
    snap.restore()


class AlignScene:
    """Pattern for lining the monitors up: straight lines every 30 mm and a
    circle on each place two monitors meet. If a monitor sits higher or lower
    than the scene thinks, the lines kink at its edge and the circle breaks."""

    STEP_MM = 30

    def __init__(self, world, s):
        self.world, self.s = world, s
        self.active = None  # name of the screen under the pointer
        self.waves, self.anims, self.dark = [], [], False

    def advance_to(self, t):
        pass

    def unit_mm(self):
        """mm per scene unit (the biggest pixels on any monitor)."""
        return getattr(self.world, "unit_mm", None) or 0.3

    def draw(self, snap, view):
        w = self.world
        snap.append_color(rgba("#03050a"), grect(0, 0, view.pw, view.ph))
        snap.save()
        snap.scale(view.scale, view.scale)
        snap.translate(gpoint(-view.x, -view.y))
        pen = Pen(snap, view, w)
        step = self.STEP_MM / self.unit_mm()
        y = w.y0 - (w.y0 % step)
        while y <= w.y1:
            major = round(y / step) % 3 == 0
            pen.line(w.x0, y, w.x1, y, 3 if major else 1.5, "#4dd9ff", 0.9 if major else 0.45)
            y += step
        mid = (w.band_top + w.band_bottom) / 2
        for a, b in zip(w.screens, w.screens[1:]):
            edge = (a.x1 + b.x) / 2
            r = 120 / self.unit_mm()
            pen.ring(edge, mid, r, 6, "#ffcc4d")
            pen.line(edge - r, mid - r, edge + r, mid + r, 4, "#ff7359")
            pen.line(edge - r, mid + r, edge + r, mid - r, 4, "#ff7359")
        shift = self.s.screen_shift
        for scr in w.screens:
            on = scr.name == self.active
            cx = scr.x + scr.w / 2
            top = scr.y + max(80, (w.band_top - scr.y) + 70) if scr.h > scr.w else scr.y + 80
            pen.text(cx, top, f"{scr.name}   picture moved {shift.get(scr.name, 0):+g} mm",
                     38, "#ffffff" if on else "#8899aa")
            pen.text(cx, top + 56, "↑ ↓ move this screen (Shift = 5 mm)   R reset" if on
                     else "point the mouse here to adjust this screen", 26, "#ffcc4d" if on else "#556677")
            pen.text(cx, top + 100, "Enter save   Esc cancel", 26, "#6bff9e" if on else "#556677")
            if on:
                for x0, y0, x1, y1 in ((scr.x, scr.y, scr.x1, scr.y), (scr.x, scr.y1, scr.x1, scr.y1),
                                       (scr.x, scr.y, scr.x, scr.y1), (scr.x1, scr.y, scr.x1, scr.y1)):
                    pen.line(x0, y0, x1, y1, 10, "#6bff9e")
        snap.restore()


class ScreenView(Gtk.Widget):
    def __init__(self, scene, screen):
        super().__init__(hexpand=True, vexpand=True)
        self.scene, self.screen = scene, screen
        self.draws = 0  # for LOGICLOOM_DEBUG

    def do_snapshot(self, snap):
        self.draws += 1
        self.scene.draw(snap, self.screen)


class LayoutPreview(Gtk.Widget):
    """All monitors in miniature, animating live (for the settings window)."""

    def __init__(self, scene=None):
        super().__init__(hexpand=True, vexpand=True)
        self.scene = scene
        self.add_tick_callback(self._tick)

    def set_scene(self, scene):
        self.scene = scene
        self.queue_draw()

    def _tick(self, _w, clock):
        if self.scene and self.get_mapped():
            self.scene.advance_to(clock.get_frame_time() / 1e6)
            self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def do_measure(self, orientation, for_size):
        return (120, 240, -1, -1) if orientation == Gtk.Orientation.VERTICAL else (200, 640, -1, -1)

    def do_snapshot(self, snap):
        if not self.scene:
            return
        w = self.scene.world
        scale = min(self.get_width() / w.w, self.get_height() / w.h)
        snap.save()
        snap.translate(gpoint((self.get_width() - w.w * scale) / 2,
                              (self.get_height() - w.h * scale) / 2))
        draw_layout(snap, self.scene, scale, gaps=(0.5, 0.5, 0.5))
        snap.restore()


class Saver(Gtk.Application):
    def __init__(self, args):
        super().__init__(application_id=APP_ID)
        self.args = args
        self.scene = None
        self.windows = []
        self.views = []
        self.start_us = None

    def do_activate(self):
        if self.windows:  # already running: a second launch is a no-op
            return
        display = Gdk.Display.get_default()
        s = self.settings = settings_mod.load()
        world = world_of(display, s)
        self.scene = AlignScene(world, s) if self.args.align else \
            Marquee(world, s, only=self.args.only)
        display.get_monitors().connect("items-changed", lambda *a: self._quit("monitors changed"))
        self.start_us = GLib.get_monotonic_time()

        by_name = {sc.name: sc for sc in world.screens}
        for mon, info in monitors(display):
            screen = by_name[info[0]]
            win = Gtk.Window(application=self, title=f"Logicloom Screensaver {screen.name}")
            win.set_decorated(False)
            view = ScreenView(self.scene, screen)
            if not self.args.align:  # the pattern only redraws when it changes
                # ceil: the fps setting is a limit, never exceeded
                every = max(1, math.ceil(mon.get_refresh_rate() / 1000 / s.fps - 1e-6))
                view.add_tick_callback(self._tick, [every, 0])
            view.set_cursor_from_name("none")
            win.set_child(view)
            if self.args.align:
                self._align_input(win, screen.name)
            else:
                self._quit_on_input(win, screen.name)
            win.connect("map", self._log_placement, screen)
            win.fullscreen_on_monitor(mon)
            win.present()
            self.windows.append(win)
            self.views.append(view)
            GLib.timeout_add(1500, self._ensure_shown, win, mon, screen.name)

        if os.environ.get("LOGICLOOM_DEBUG"):
            GLib.timeout_add(2000, self._debug_report)
        if self.args.duration:
            GLib.timeout_add(int(self.args.duration * 1000), lambda: self._quit("--duration reached"))

    def _tick(self, view, clock, pace):
        every, count = pace
        pace[1] = (count + 1) % every
        if count == 0:
            self.scene.advance_to(clock.get_frame_time() / 1e6)
            view.queue_draw()
            if self.scene.dark:
                # black now: this was the last frame; stop the frame clock
                # (input still quits; only the drawing rests)
                return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    # -- line-up mode -----------------------------------------------------------
    def _align_input(self, win, name):
        """Arrow keys move the picture on the screen under the pointer."""
        def point(*_a):
            if self.scene.active != name:
                self.scene.active = name
                self._redraw_all()

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", point)
        motion.connect("motion", point)
        win.add_controller(motion)

        def key(_c, kv, _code, state):
            k = Gdk.keyval_name(kv) or ""
            step = 5.0 if state & Gdk.ModifierType.SHIFT_MASK else 1.0
            active = self.scene.active or name
            if k in ("Up", "KP_Up"):
                self._shift(active, +step)
            elif k in ("Down", "KP_Down"):
                self._shift(active, -step)
            elif k in ("r", "R"):
                self._shift(active, None)
            elif k in ("Return", "KP_Enter"):
                self._align_save()
            elif k == "Escape":
                self._quit("line-up cancelled")
            return True

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", key)
        win.add_controller(keys)

    def _align_save(self):
        fresh = settings_mod.load()  # keep anything else changed meanwhile
        fresh.screen_shift = dict(self.settings.screen_shift)
        settings_mod.save(fresh)
        self._quit(f"saved screen_shift {settings_mod.write_per_screen(fresh.screen_shift)}")

    def _shift(self, name, delta):
        shift = self.settings.screen_shift
        if delta is None:
            shift.pop(name, None)
        else:
            shift[name] = round(shift.get(name, 0.0) + delta, 1)
            if shift[name] == 0:
                del shift[name]
        world = world_of(Gdk.Display.get_default(), self.settings)
        self.scene.world = world
        by_name = {sc.name: sc for sc in world.screens}
        for view in self.views:
            view.screen = by_name[view.screen.name]
        self._redraw_all()

    def _redraw_all(self):
        for view in self.views:
            view.queue_draw()

    def _ensure_shown(self, win, mon, name):
        """Now and then the compositor leaves one window unshown for many
        seconds, so that monitor keeps showing the desktop. Ask again."""
        if win.get_mapped() and win.is_fullscreen():
            return GLib.SOURCE_REMOVE
        print(f"window for {name} not shown after 1.5 s: asking again", flush=True)
        win.fullscreen_on_monitor(mon)
        win.present()
        return GLib.SOURCE_CONTINUE  # check again in 1.5 s

    def _debug_report(self):
        """LOGICLOOM_DEBUG=1: every 2 s, frames each monitor drew and where the waves are."""
        age = (GLib.get_monotonic_time() - self.start_us) / 1e6
        parts = []
        for view in self.views:
            win = view.get_root()
            parts.append(f"{view.screen.name}:{'shown' if win.get_mapped() else 'HIDDEN'}"
                         f"/{view.draws}fr")
            view.draws = 0
        waves = " ".join(f"[{w.index}:{w.text[:10]} x={w.x:.0f}..{w.x + w.w:.0f}]"
                         for w, _a, _b in self.scene.waves)
        print(f"t={age:5.1f}  {'  '.join(parts)}  waves {waves}", flush=True)
        return GLib.SOURCE_CONTINUE

    def _log_placement(self, win, screen):
        def report():
            surface = win.get_surface()
            mon = surface and win.get_display().get_monitor_at_surface(surface)
            got = mon.get_connector() if mon else "?"
            print(f"window for {screen} shown on {got}, "
                  f"size {win.get_width()}x{win.get_height()}", flush=True)
        GLib.timeout_add(700, report)

    def _in_grace(self):
        return GLib.get_monotonic_time() - self.start_us < GRACE * 1e6

    def _quit(self, reason):
        # Logged so "it closed by itself" can be traced in the journal.
        age = (GLib.get_monotonic_time() - self.start_us) / 1e6
        print(f"quitting after {age:.1f} s: {reason}", flush=True)
        self.quit()

    def _quit_on_input(self, win, name):
        # Keys and clicks are always deliberate: quit at once, even at start.
        def quit_now(what):
            self._quit(f"{what} on {name}")

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_a: (
            quit_now(f"key {Gdk.keyval_name(kv)}"), True)[1])
        win.add_controller(keys)

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", lambda g, *_a: quit_now(f"click button {g.get_current_button()}"))
        win.add_controller(click)

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", lambda *a: (quit_now("scroll"), True)[1])
        win.add_controller(scroll)

        # Mouse movement is the tricky one. Wayland only gives positions
        # relative to this window, so when the window is mapped, resized or
        # moved the position jumps although the mouse did not move (that
        # closed the saver 12 s in when a late window went fullscreen).
        # After any such change: forget the anchor and let it settle.
        state = {"anchor": None, "settle_until": 0}

        def settle(why):
            state["anchor"] = None
            state["settle_until"] = GLib.get_monotonic_time() + SETTLE * 1e6

        def moved(_ctl, x, y):
            if self._in_grace() or GLib.get_monotonic_time() < state["settle_until"]:
                state["anchor"] = (x, y)  # pointer still settling: re-anchor
                return
            if state["anchor"] is None:
                state["anchor"] = (x, y)
                return
            ax, ay = state["anchor"]
            if math.hypot(x - ax, y - ay) > MOVE_QUIT_PX:
                quit_now(f"mouse moved {math.hypot(x - ax, y - ay):.0f} px "
                         f"({ax:.0f},{ay:.0f} -> {x:.0f},{y:.0f})")

        def entered(_ctl, x, y):
            print(f"pointer entered {name} at {x:.0f},{y:.0f}", flush=True)
            settle("enter")

        win.connect("map", lambda *_a: settle("map"))
        win.connect("notify::default-width", lambda *_a: settle("resize"))
        win.connect("notify::default-height", lambda *_a: settle("resize"))
        win.connect("notify::fullscreened", lambda *_a: settle("fullscreen"))

        def watch_surface(*_a):
            surface = win.get_surface()
            if surface is not None:
                surface.connect("layout", lambda *_b: settle("layout"))
        win.connect("realize", watch_surface)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", moved)
        motion.connect("enter", entered)
        win.add_controller(motion)


def offline_scene(args):
    Gtk.init()
    display = Gdk.Display.get_default()
    s = settings_mod.load()
    world = world_of(display, s)
    if getattr(args, "align", False):
        return display, AlignScene(world, s)
    return display, Marquee(world, s, only=args.only, seed=args.seed)


def snapshot(args):
    display, scene = offline_scene(args)
    t = 0.0
    scene.advance_to(t)
    while t < args.at:
        t += 1 / 60
        scene.advance_to(t)
    w = scene.world
    s = args.scale
    snap = Gtk.Snapshot()
    draw_layout(snap, scene, s)
    renderer = Gsk.GLRenderer()
    renderer.realize_for_display(display)
    tex = renderer.render_texture(snap.to_node(), grect(0, 0, w.w * s, w.h * s))
    tex.save_to_png(args.snapshot)
    renderer.unrealize()
    for wave, anim, _b in scene.waves:
        print(f"wave {wave.index} {wave.text!r} [{anim.key if anim else '-'}] "
              f"x={wave.x:.0f}..{wave.x + wave.w:.0f}")
    print(f"wrote {args.snapshot} ({tex.get_width()}x{tex.get_height()})")


def profile(args):
    """Draw cost per screen per frame, over a minute of simulated time."""
    _display, scene = offline_scene(args)
    t = 0.0
    scene.advance_to(t)
    worst, total, n = 0.0, 0.0, 0
    while t < args.at:
        t += 1 / 72
        scene.advance_to(t)
        for screen in scene.world.screens:
            a = time.perf_counter()
            snap = Gtk.Snapshot()
            scene.draw(snap, screen)
            snap.to_node()
            d = time.perf_counter() - a
            worst, total, n = max(worst, d), total + d, n + 1
    per_s = 72 * 2 + 60
    print(f"{n} draws over {args.at:.0f} s: average {total / n * 1000:.2f} ms, "
          f"worst {worst * 1000:.2f} ms per screen")
    print(f"about {total / n * per_s * 100:.0f}% of one CPU core at 72+72+60 fps")
    broken = [a.key for a in scene.anims if a.broken]
    if broken:
        print(f"BROKEN animations: {', '.join(broken)}")
        return 1
    return 0


def main():
    p = argparse.ArgumentParser(description="Logicloom marquee across every monitor.")
    p.add_argument("--duration", type=float, default=0, help="quit after N seconds")
    p.add_argument("--only", metavar="NAME", help="show only this animation")
    p.add_argument("--align", action="store_true",
                   help="show the line-up pattern; arrow keys move a screen's picture")
    p.add_argument("--snapshot", metavar="PNG", help="render the layout to a PNG and exit")
    p.add_argument("--profile", action="store_true", help="time the drawing and exit")
    p.add_argument("--at", type=float, default=8.0, help="seconds to simulate first")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--scale", type=float, default=0.3, help="snapshot scale")
    args = p.parse_args()
    if args.only:
        from marquee import discover
        found = discover()
        if args.only not in found:
            print(f"no animation called {args.only!r}; available: {', '.join(sorted(found))}",
                  file=sys.stderr)
            return 2
    if args.snapshot:
        snapshot(args)
        return 0
    if args.profile:
        if args.at == 8.0:
            args.at = 60.0
        return profile(args)
    return Saver(args).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
