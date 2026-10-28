#!/usr/bin/env python3
"""Starts the ScreenWave after the keyboard and mouse have been
idle for `idle_minutes` (settings.ini).

Uses GNOME's own idle monitor (org.gnome.Mutter.IdleMonitor), so it works on
Wayland where X11 screensavers cannot see input. On other desktops it polls
the freedesktop idle time (org.freedesktop.ScreenSaver) every 5 s. It re-reads the settings
file whenever it changes. It does not start the screensaver when:
  - the screen is locked,
  - an app is inhibiting idle (video playing, a presentation),
  - ~/.config/screenwave/paused exists (touch it to pause, delete to resume).

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
FD_BUS = "org.freedesktop.ScreenSaver"  # KDE and other non-GNOME desktops
FD_PATH = "/org/freedesktop/ScreenSaver"


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
        # GNOME: (re-)add the watch whenever gnome-shell (re)starts.
        # Other desktops (KDE, ...): poll the freedesktop idle time instead.
        self.poll_id = 0
        self.fired_this_idle = False
        Gio.bus_watch_name_on_connection(self.bus, IDLE_BUS, Gio.BusNameWatcherFlags.NONE,
                                         lambda *a: self._gnome_appeared(),
                                         lambda *a: self._gnome_vanished())

    def _gnome_appeared(self):
        if self.poll_id:
            GLib.source_remove(self.poll_id)
            self.poll_id = 0
        self._arm(force=True)

    def _gnome_vanished(self):
        self.watch_id = None
        if not self.poll_id:
            log(f"no {IDLE_BUS}: polling {FD_BUS} for idle time instead")
            self.poll_id = GLib.timeout_add_seconds(5, self._poll)

    def _poll(self):
        """Non-GNOME desktops: check the session idle time every 5 s."""
        try:
            (idle_ms,) = self._call(FD_BUS, FD_PATH, FD_BUS, "GetSessionIdleTime")
        except GLib.Error as e:
            log(f"cannot read the idle time ({e.message}); trying again in 5 s")
            return GLib.SOURCE_CONTINUE
        threshold = int(S.load().idle_minutes * 60_000)
        if idle_ms < threshold:
            self.fired_this_idle = False  # input since: the next idle may start it
        elif not self.fired_this_idle:
            self.fired_this_idle = True
            self._start("idle")
        return GLib.SOURCE_CONTINUE

    def _call(self, name, path, iface, method, args=None):
        return self.bus.call_sync(name, path, iface, method, args, None,
                                  Gio.DBusCallFlags.NONE, 2000, None).unpack()

    def _arm(self, force=False):
        if self.poll_id:
            return  # polling reads the setting each time
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
        if fired == self.watch_id:
            self._start("idle")

    def _start(self, why):
        reason = self._skip_reason()
        if reason:
            log(f"{why}, not starting: {reason}")
            return
        log(f"{why}: starting the screensaver")
        self.saver = subprocess.Popen([sys.executable, str(SAVER)])
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, self.saver.pid, self._saver_exited)

    def _saver_exited(self, pid, status):
        # reap it (no zombie), and keep crashes visible in the journal
        if self.saver and self.saver.pid == pid:
            self.saver.returncode = status
        if status:
            log(f"screensaver exited with status {status}")

    def _skip_reason(self):
        if self.saver and self.saver.poll() is None:
            return "already running"
        if S.PAUSE_FILE.exists():
            return f"paused ({S.PAUSE_FILE})"
        # GNOME first, then the freedesktop interface other desktops offer
        checks = (
            ("screen is locked", "org.gnome.ScreenSaver", "/org/gnome/ScreenSaver",
             "org.gnome.ScreenSaver", "GetActive", None),
            ("an app is inhibiting idle", "org.gnome.SessionManager", "/org/gnome/SessionManager",
             "org.gnome.SessionManager", "IsInhibited", GLib.Variant("(u)", (INHIBIT_IDLE,))),
            ("screen is locked", FD_BUS, FD_PATH, FD_BUS, "GetActive", None),
        )
        answered = False
        for reason, name, path, iface, method, args in checks:
            try:
                (yes,) = self._call(name, path, iface, method, args)
            except GLib.Error:
                continue
            answered = True
            if yes:
                return reason
        if not answered:
            log("could not ask the desktop whether the screen is locked; starting anyway")
        return None


def main():
    IdleWatcher()
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
