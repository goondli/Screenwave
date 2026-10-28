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
  saver.py --profile [--only neural]
                                    time the drawing, per screen per frame
"""
import argparse
import math
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Gdk, GLib, Gsk, Gtk  # noqa: E402

import settings as settings_mod  # noqa: E402
from kit import Screen, World, gpoint, grect, rgba  # noqa: E402
from marquee import Marquee  # noqa: E402

APP_ID = "in.maridian.LogicloomSaver"
GRACE = 1.2          # ignore input this long after start (pointer settles)
MOVE_QUIT_PX = 14


def monitors(display):
    out = []
    ms = display.get_monitors()
    for i in range(ms.get_n_items()):
        m = ms.get_item(i)
        g = m.get_geometry()
        out.append((m, Screen(g.x, g.y, g.width, g.height, m.get_connector() or f"mon{i}")))
    return out


def world_of(display):
    return World([s for _, s in monitors(display)])


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
        scene.draw(snap, s)
        snap.pop()
        snap.restore()
    snap.restore()


class ScreenView(Gtk.Widget):
    def __init__(self, scene, screen):
        super().__init__(hexpand=True, vexpand=True)
        self.scene, self.screen = scene, screen

    def do_snapshot(self, snap):
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
        self.start_us = None

    def do_activate(self):
        if self.windows:  # already running: a second launch is a no-op
            return
        display = Gdk.Display.get_default()
        mons = monitors(display)
        s = settings_mod.load()
        self.scene = Marquee(World([sc for _, sc in mons]), s, only=self.args.only)
        display.get_monitors().connect("items-changed", lambda *a: self.quit())
        self.start_us = GLib.get_monotonic_time()

        for mon, screen in mons:
            win = Gtk.Window(application=self, title=f"Logicloom Screensaver {screen.name}")
            win.set_decorated(False)
            view = ScreenView(self.scene, screen)
            every = max(1, round(mon.get_refresh_rate() / 1000 / s.fps))
            view.add_tick_callback(self._tick, [every, 0, False])
            view.set_cursor_from_name("none")
            win.set_child(view)
            self._quit_on_input(win)
            win.connect("map", self._log_placement, screen)
            win.fullscreen_on_monitor(mon)
            win.present()
            self.windows.append(win)

        if self.args.duration:
            GLib.timeout_add(int(self.args.duration * 1000), self.quit)

    def _tick(self, view, clock, pace):
        every, count, drew_dark = pace
        pace[1] = (count + 1) % every
        if count == 0 and not drew_dark:
            self.scene.advance_to(clock.get_frame_time() / 1e6)
            view.queue_draw()
            pace[2] = self.scene.dark  # black now: draw it once, then rest
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

    def _quit_on_input(self, win):
        def quit_now(*_):
            if not self._in_grace():
                self.quit()

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda *a: (quit_now(), True)[1])
        win.add_controller(keys)

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", quit_now)
        win.add_controller(click)

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", lambda *a: (quit_now(), True)[1])
        win.add_controller(scroll)

        anchor = {}

        def moved(_ctl, x, y):
            if self._in_grace():
                anchor["p"] = (x, y)  # pointer still settling: re-anchor
                return
            ax, ay = anchor.setdefault("p", (x, y))
            if math.hypot(x - ax, y - ay) > MOVE_QUIT_PX:
                self.quit()

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", moved)
        motion.connect("enter", lambda *a: anchor.clear())  # new window, new anchor
        win.add_controller(motion)


def offline_scene(args):
    Gtk.init()
    display = Gdk.Display.get_default()
    world = world_of(display)
    return display, Marquee(world, settings_mod.load(), only=args.only, seed=args.seed)


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
    p.add_argument("--snapshot", metavar="PNG", help="render the layout to a PNG and exit")
    p.add_argument("--profile", action="store_true", help="time the drawing and exit")
    p.add_argument("--at", type=float, default=8.0, help="seconds to simulate first")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--scale", type=float, default=0.3, help="snapshot scale")
    args = p.parse_args()
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
