#!/usr/bin/env python3
"""Starts the Logicloom Screensaver after the keyboard and mouse have been
idle for `idle_minutes` (settings.ini).

Uses GNOME's own idle monitor (org.gnome.Mutter.IdleMonitor), so it works on
Wayland where X11 screensavers cannot see input. It re-reads the settings
file whenever it changes. It does not start the screensaver when:
  - the screen is locked,
  - an app is inhibiting idle (video playing, a presentation),
  - ~/.config/logicloom-saver/paused exists (touch it to pause, delete to resume).

GNOME's own screen blank and lock settings keep working as before.
"""
import subprocess
import sys
from pathlib import Path

from gi.repository import Gio, GLib

import settings as S

IDLE_BUS = "org.gnome.Mutter.IdleMonitor"
IDLE_PATH = "/org/gnome/Mutter/IdleMonitor/Core"
SAVER = Path(__file__).resolve().with_name("saver.py")
INHIBIT_IDLE = 8  # GsmInhibitorFlag.IDLE


def log(msg):
    print(msg, flush=True)


class IdleWatcher:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.watch_id = None
        self.idle_ms = None
        self.saver = None
        self.bus.signal_subscribe(IDLE_BUS, IDLE_BUS, "WatchFired", IDLE_PATH,
                                  None, Gio.DBusSignalFlags.NONE, self._fired)
        S.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Watch the folder: the settings window saves by renaming a new file
        # over the old one, which a monitor on the file itself can miss.
        self.monitor = Gio.File.new_for_path(str(S.CONFIG_DIR)).monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.monitor.connect("changed", self._config_changed)
        # (Re-)add the watch whenever gnome-shell (re)starts.
        Gio.bus_watch_name_on_connection(self.bus, IDLE_BUS, Gio.BusNameWatcherFlags.NONE,
                                         lambda *a: self._arm(force=True), None)

    def _call(self, name, path, iface, method, args=None):
        return self.bus.call_sync(name, path, iface, method, args, None,
                                  Gio.DBusCallFlags.NONE, 2000, None).unpack()

    def _arm(self, force=False):
        idle_ms = int(S.load().idle_minutes * 60_000)
        if idle_ms == self.idle_ms and not force:
            return
        try:
            if self.watch_id is not None and not force:
                self._call(IDLE_BUS, IDLE_PATH, IDLE_BUS, "RemoveWatch",
                           GLib.Variant("(u)", (self.watch_id,)))
            (self.watch_id,) = self._call(IDLE_BUS, IDLE_PATH, IDLE_BUS, "AddIdleWatch",
                                          GLib.Variant("(t)", (idle_ms,)))
            self.idle_ms = idle_ms
            log(f"watching for {idle_ms / 60_000:g} min idle (watch {self.watch_id})")
        except GLib.Error as e:
            log(f"could not set the idle watch: {e.message}")

    def _config_changed(self, _mon, file, other, event):
        names = {f.get_basename() for f in (file, other) if f}
        if S.SETTINGS_FILE.name in names and event in (
                Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED,
                Gio.FileMonitorEvent.RENAMED, Gio.FileMonitorEvent.MOVED_IN):
            self._arm()

    def _fired(self, _conn, _sender, _path, _iface, _signal, params):
        (fired,) = params.unpack()
        if fired != self.watch_id:
            return
        reason = self._skip_reason()
        if reason:
            log(f"idle, not starting: {reason}")
            return
        log("idle: starting the screensaver")
        self.saver = subprocess.Popen([sys.executable, str(SAVER)])

    def _skip_reason(self):
        if self.saver and self.saver.poll() is None:
            return "already running"
        if S.PAUSE_FILE.exists():
            return f"paused ({S.PAUSE_FILE})"
        try:
            (locked,) = self._call("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver",
                                   "org.gnome.ScreenSaver", "GetActive")
            if locked:
                return "screen is locked"
            (inhibited,) = self._call("org.gnome.SessionManager", "/org/gnome/SessionManager",
                                      "org.gnome.SessionManager", "IsInhibited",
                                      GLib.Variant("(u)", (INHIBIT_IDLE,)))
            if inhibited:
                return "an app is inhibiting idle"
        except GLib.Error as e:
            log(f"status check failed, starting anyway: {e.message}")
        return None


def main():
    IdleWatcher()
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
