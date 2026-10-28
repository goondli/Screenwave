#!/usr/bin/env python3
"""ScreenWave: the settings window.

Changes show at once in the live preview at the top; Apply saves them to
~/.config/screenwave/settings.ini (Revert drops them). Enable / Disable
turn the automatic start on idle on and off.
"""
import os
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

import settings as S  # noqa: E402
from marquee import ANIMATIONS_DIR, Marquee, discover  # noqa: E402
from saver import LayoutPreview, monitors, world_of  # noqa: E402

APP_ID = "io.github.goondli.ScreenWave"
HERE = Path(__file__).resolve().parent
SERVICE = "screenwave.service"
UNIT_DST = Path.home() / ".config" / "systemd" / "user" / SERVICE
PREVIEW_INI = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "screenwave-preview.ini"


def rgba_of(hex_color):
    c = Gdk.RGBA()
    c.parse(hex_color)
    return c


def hex_of(c):
    return "#{:02x}{:02x}{:02x}".format(*(round(v * 255) for v in (c.red, c.green, c.blue)))


def systemctl(*args):
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
    except OSError as e:
        return 1, str(e)
    return r.returncode, (r.stdout + r.stderr).strip()


def unit_text():
    """The user service, pointing at wherever this folder is."""
    here = str(HERE).replace("%", "%%")  # % is special in unit files
    return (HERE / "screenwave.service.in").read_text().replace("@HERE@", here)


def monitor_label(name, w, h, wmm, hmm, inches):
    size = f'{inches:g}"' if inches else (f"{wmm}×{hmm} mm" if wmm else "size unknown")
    shape = "portrait" if h > w else "landscape"
    return f"{name}  ·  {size}  ·  {w}×{h} {shape}"


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="ScreenWave")
        self.set_default_size(820, 980)
        self.warnings = []
        self.saved = S.load(warn=self.warnings.append)  # what is on disk
        self.s = self.saved.copy()                         # what the window shows
        self.load_errors = {}
        self.anims = discover(errors=self.load_errors)
        self.display = Gdk.Display.get_default()
        self.world = world_of(self.display, self.s)
        self._closing = False
        self.connect("close-request", self.on_close_request)
        # pick up edits made to the file by hand ("Open settings file")
        self._file_monitor = Gio.File.new_for_path(str(S.SETTINGS_FILE)).monitor_file(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
        self._file_monitor.connect("changed", self.on_file_changed)

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title="ScreenWave")
        header.set_title_widget(self.title)
        run = Gtk.Button(label="Preview on screens")
        run.set_tooltip_text("Play it now on the monitors with the settings shown here, "
                             "applied or not. Move the mouse to stop.")
        run.connect("clicked", self.on_run)
        header.pack_start(run)
        menu = Gio.Menu()
        menu.append("Open settings file", "win.open-file")
        menu.append("Reset to defaults…", "win.reset")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        self.apply_btn = Gtk.Button(label="Apply")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.set_tooltip_text("Save these settings; the screensaver uses them from "
                                        "its next start")
        self.apply_btn.connect("clicked", lambda *_: self.apply())
        header.pack_end(self.apply_btn)
        self.revert_btn = Gtk.Button(label="Revert")
        self.revert_btn.set_tooltip_text("Drop the changes made since the last Apply")
        self.revert_btn.connect("clicked", lambda *_: self.revert())
        header.pack_end(self.revert_btn)
        view.add_top_bar(header)

        self.preview = LayoutPreview()
        self.preview.set_size_request(-1, 200)
        frame = Gtk.Frame(margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        frame.set_child(self.preview)

        self.page = Adw.PreferencesPage()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(frame)
        box.append(self.page)
        self.page.set_vexpand(True)
        view.set_content(box)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        for name, fn in (("open-file", self.on_open_file), ("reset", self.on_reset)):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", fn)
            self.add_action(act)

        self.build()
        self.rebuild_preview()
        self.update_dirty()
        for w in self.warnings:
            self.toast(w)

    # -- state ----------------------------------------------------------------
    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def dirty(self):
        return S.render(self.s) != S.render(self.saved)

    def update_dirty(self):
        d = self.dirty()
        self.apply_btn.set_sensitive(d)
        self.revert_btn.set_sensitive(d)
        self.title.set_subtitle("Changes not applied yet" if d else "All changes applied")

    def changed(self, *_):
        """Called by every control: preview now, mark unapplied."""
        self.rebuild_preview()
        self.update_dirty()

    def apply(self):
        try:
            S.save(self.s)
        except OSError as e:
            self.toast(f"Could not save: {e}")
            return False
        self.saved = self.s.copy()
        self.update_dirty()
        self.toast("Applied. The screensaver uses these settings from its next start.")
        return True

    def revert(self):
        self.s = self.saved.copy()
        self.build()
        self.rebuild_preview()
        self.update_dirty()
        self.toast("Changes dropped")

    def on_close_request(self, *_):
        if self._closing or not self.dirty():
            return False
        dlg = Adw.AlertDialog(heading="Apply your changes?",
                              body="Some changes are not applied yet. Without Apply the "
                                   "screensaver keeps the old settings.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("discard", "Close without applying")
        dlg.add_response("apply", "Apply and close")
        dlg.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("apply")

        def done(d, result):
            answer = d.choose_finish(result)
            if answer == "apply" and not self.apply():
                return
            if answer in ("apply", "discard"):
                self._closing = True
                self.close()
        dlg.choose(self, None, done)
        return True  # stay open until answered

    def on_file_changed(self, _mon, _file, _other, event):
        if event not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED,
                         Gio.FileMonitorEvent.RENAMED, Gio.FileMonitorEvent.MOVED_IN):
            return
        try:
            text = S.SETTINGS_FILE.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        if text == S.render(self.saved):
            return  # our own Apply
        had_changes = self.dirty()
        self.saved = S.load(warn=self.toast)
        if had_changes:
            self.update_dirty()
            self.toast("The settings file changed outside this window. Revert loads it; "
                       "Apply replaces it with what is shown here.")
            return
        self.s = self.saved.copy()
        self.build()
        self.rebuild_preview()
        self.update_dirty()
        self.toast("Settings file changed outside this window: reloaded")

    def rebuild_preview(self):
        # screen settings change the layout itself
        self.world = world_of(self.display, self.s)
        # quiet: the page already shows a "Not found" row for missing files
        self.preview.set_scene(Marquee(self.world, self.s.copy(), animations=self.anims, quiet=True))

    # -- control helpers --------------------------------------------------------
    def spin(self, group, title, subtitle, key, lo, hi, step, digits=0):
        # the settings file's own limits win, so every valid value shows
        parse = S.SPEC[key][2]
        lo, hi = getattr(parse, "lo", lo), getattr(parse, "hi", hi)
        row = Adw.SpinRow.new_with_range(lo, hi, step)
        row.set_title(title)
        if subtitle:
            row.set_subtitle(subtitle)
        row.set_digits(digits)
        row.set_value(getattr(self.s, key))

        def on_value(r, _p):
            v = r.get_value()
            setattr(self.s, key, int(round(v)) if digits == 0 else round(v, digits))
            self.changed()
        row.connect("notify::value", on_value)
        group.add(row)
        return row

    def color(self, group, title, key):
        row = Adw.ActionRow(title=title)
        btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                    valign=Gtk.Align.CENTER)
        btn.set_rgba(rgba_of(getattr(self.s, key)))

        def on_rgba(b, _p):
            setattr(self.s, key, hex_of(b.get_rgba()))
            self.changed()
        btn.connect("notify::rgba", on_rgba)
        row.add_suffix(btn)
        row.set_activatable_widget(btn)
        group.add(row)

    def combo(self, group, title, key, options, subtitle=None):
        """options: [(value, label)]"""
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([lbl for _v, lbl in options]))
        if subtitle:
            row.set_subtitle(subtitle)
        values = [v for v, _l in options]
        row.set_selected(values.index(getattr(self.s, key)) if getattr(self.s, key) in values else 0)

        def on_sel(r, _p):
            setattr(self.s, key, values[r.get_selected()])
            self.changed()
        row.connect("notify::selected", on_sel)
        group.add(row)

    # -- the page -------------------------------------------------------------
    def build(self):
        for g in list(getattr(self, "_groups", [])):
            self.page.remove(g)
        self._groups = []

        def group(title, description=None):
            g = Adw.PreferencesGroup(title=title)
            if description:
                g.set_description(description)
            self.page.add(g)
            self._groups.append(g)
            return g

        # on / off
        g = group("Screensaver")
        self.state_row = Adw.ActionRow()
        self.enable_btn = Gtk.Button(label="Enable", valign=Gtk.Align.CENTER)
        self.enable_btn.add_css_class("suggested-action")
        self.enable_btn.connect("clicked", lambda *_: self.set_enabled(True))
        self.disable_btn = Gtk.Button(label="Disable", valign=Gtk.Align.CENTER)
        self.disable_btn.add_css_class("destructive-action")
        self.disable_btn.connect("clicked", lambda *_: self.set_enabled(False))
        self.state_row.add_suffix(self.enable_btn)
        self.state_row.add_suffix(self.disable_btn)
        g.add(self.state_row)
        self.show_state()

        # monitors
        g = group("Monitors", "Choose the monitors it plays on: one, two, three, four or more.")
        self.monitor_names = [info[0] for _m, info in monitors(self.display)]
        chosen = self.chosen_monitors()
        for _mon, (name, _x, _y, w, h, wmm, hmm, inches) in monitors(self.display):
            row = Adw.SwitchRow(title=monitor_label(name, w, h, wmm, hmm, inches))
            row.set_active(name in chosen)
            row.connect("notify::active", self.on_monitor_toggle, name)
            g.add(row)
        self.combo(g, "Monitors left out", "unused_monitors",
                   [("black", "Go black"), ("desktop", "Keep showing the desktop")])

        # text
        g = group("Marquee text", "Each line travels across the screens as one wave, in turn.")
        self.lines_group = g
        self.line_rows = []
        self.add_line_button = None  # a rebuild starts a fresh group
        for text in self.s.lines:
            self.add_line_row(text)
        add = Adw.ButtonRow(title="Add line", start_icon_name="list-add-symbolic")
        add.connect("activated", lambda *_: (self.add_line_row(""), self.sync_lines()))
        g.add(add)
        self.add_line_button = add

        g = group("Text style")
        row = Adw.ActionRow(title="Font")
        fbtn = Gtk.FontDialogButton(dialog=Gtk.FontDialog(), valign=Gtk.Align.CENTER,
                                    level=Gtk.FontLevel.FACE, use_font=True)
        fbtn.set_font_desc(Pango.FontDescription.from_string(self.s.font))

        def on_font(b, _p):
            desc = b.get_font_desc().copy()
            desc.unset_fields(Pango.FontMask.SIZE)
            self.s.font = desc.to_string()
            self.changed()
        fbtn.connect("notify::font-desc", on_font)
        row.add_suffix(fbtn)
        g.add(row)
        self.spin(g, "Text size", "Height of the letters, in pixels", "text_size", 20, 900, 10)
        self.color(g, "Text colour", "text_color")
        self.color(g, "Glow colour", "glow_color")
        self.spin(g, "Ripple height", "How far letters wave up and down; 0 = straight",
                  "wave_height", 0, 400, 2)
        self.spin(g, "Text position", "Height on the screens, % from top of the shared band",
                  "lane", 0, 100, 5)

        # motion
        g = group("Motion")
        self.spin(g, "Speed", "Pixels per second", "speed", 20, 4000, 20)
        self.combo(g, "Direction", "direction",
                   [("left_to_right", "Left to right"), ("right_to_left", "Right to left")])
        self.spin(g, "Gap between waves", "Seconds", "wave_gap", 0, 120, 0.5, digits=1)

        # animations
        g = group("Animations", "Ride along with the waves, in turn. Each is one file in the "
                  "animations folder - add your own there.")
        order = [k for k in self.s.enabled if k in self.anims] + \
            [k for k in sorted(self.anims) if k not in self.s.enabled]
        for key in order:
            a = self.anims[key]
            row = Adw.SwitchRow(title=a.name, subtitle=a.description or f"{key}.py")
            row.set_active(key in self.s.enabled)
            row.connect("notify::active", self.on_anim_toggle, key)
            g.add(row)
        for key, err in sorted(self.load_errors.items()):
            g.add(Adw.ActionRow(title=f"Could not load: {key}.py", subtitle=err))
        missing = [k for k in self.s.enabled if k not in self.anims and k not in self.load_errors]
        if missing:
            g.add(Adw.ActionRow(title="Not found: " + ", ".join(missing),
                                subtitle="Enabled in settings but no matching file"))
        self.combo(g, "Order", "order", [("in_turn", "In turn"), ("random", "Random")])

        row = Adw.ActionRow(title="Animation colours")
        self.palette_box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        row.add_suffix(self.palette_box)
        g.add(row)
        self.fill_palette()

        buttons = Gtk.Box(spacing=8, margin_top=8, homogeneous=True)
        for label, fn in (("Open animations folder", self.on_open_folder),
                          ("New animation…", self.on_new_animation),
                          ("Reload animations", self.on_reload)):
            b = Gtk.Button(label=label)
            b.connect("clicked", fn)
            buttons.append(b)
        g.add(buttons)

        # sizes and heights
        g = group("Sizes and heights", "Monitors of different sizes show everything at the same "
                  "real size and height. If one is mounted higher or lower, line them up.")
        row = Adw.SwitchRow(title="Same size on every monitor",
                            subtitle="Zoom smaller-pixel monitors to match the others")
        row.set_active(self.s.match_sizes)

        def on_match(r, _p):
            self.s.match_sizes = r.get_active()
            self.changed()
        row.connect("notify::active", on_match)
        g.add(row)
        self.combo(g, "Monitors are level at", "level",
                   [("bottoms", "Bottom edges"), ("centres", "Centres"), ("tops", "Top edges"),
                    ("gnome_layout", "As in the display settings")],
                   subtitle="Side-by-side monitors only; stacked ones follow the display settings")
        for _mon, (name, _x, _y, w, h, wmm, hmm, inches) in monitors(self.display):
            spin = Adw.SpinRow.new_with_range(-500, 500, 1)
            spin.set_title(monitor_label(name, w, h, wmm, hmm, inches))
            spin.set_subtitle("Move this monitor's picture up (+) or down (-), in mm")
            spin.set_digits(1)
            spin.set_value(self.s.screen_shift.get(name, 0.0))

            def on_shift(r, _p, name=name):
                v = round(r.get_value(), 1)
                if v:
                    self.s.screen_shift[name] = v
                else:
                    self.s.screen_shift.pop(name, None)
                self.changed()
            spin.connect("notify::value", on_shift)
            g.add(spin)
        align = Adw.ButtonRow(title="Line up screens…", start_icon_name="view-grid-symbolic")
        align.set_tooltip_text("Shows lines across all monitors. Point at one, press "
                               "Up/Down until the lines run straight, then Enter.")
        align.connect("activated", self.on_align)
        g.add(align)

        # running
        g = group("When it runs")
        self.spin(g, "Start after", "Minutes without keyboard or mouse", "idle_minutes",
                  0.5, 1440, 0.5, digits=1)
        self.spin(g, "Play for", "Minutes, then the screens fade to black; 0 = until you move",
                  "run_minutes", 0, 1440, 1, digits=1)
        self.color(g, "Background", "background")
        self.spin(g, "Frame rate limit", "Frames per second on fast screens; lower uses less CPU",
                  "fps", 10, 240, 6)

    # -- monitors ----------------------------------------------------------------
    def chosen_monitors(self):
        present = [n for n in self.monitor_names]
        picked = [n for n in self.s.monitors if n in present]
        return picked or present  # nothing chosen (or none plugged in) = all

    def on_monitor_toggle(self, row, _p, name):
        chosen = [n for n in self.chosen_monitors() if n != name]
        if row.get_active():
            chosen.append(name)
        if not chosen:
            self.toast("Keep at least one monitor")
            row.set_active(True)
            return
        # keep the display order; all of them is stored as "all" (empty)
        chosen = [n for n in self.monitor_names if n in chosen]
        self.s.monitors = [] if len(chosen) == len(self.monitor_names) else chosen
        self.changed()

    # -- lines ------------------------------------------------------------------
    def add_line_row(self, text):
        row = Adw.EntryRow(title="Line")
        row.set_text(text)
        row.connect("changed", lambda *_: self.sync_lines())
        rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                        tooltip_text="Remove this line")
        rm.add_css_class("flat")
        rm.connect("clicked", self.on_remove_line, row)
        row.add_suffix(rm)
        self.line_rows.append(row)
        # keep the "Add line" button last
        if getattr(self, "add_line_button", None):
            self.lines_group.remove(self.add_line_button)
            self.lines_group.add(row)
            self.lines_group.add(self.add_line_button)
        else:
            self.lines_group.add(row)
        return row

    def on_remove_line(self, _btn, row):
        if len(self.line_rows) <= 1:
            self.toast("Keep at least one line")
            return
        self.line_rows.remove(row)
        self.lines_group.remove(row)
        self.sync_lines()

    def sync_lines(self):
        lines = [r.get_text().strip() for r in self.line_rows if r.get_text().strip()]
        if lines:
            self.s.lines = lines
            self.changed()

    # -- palette ------------------------------------------------------------------
    def fill_palette(self):
        child = self.palette_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.palette_box.remove(child)
            child = nxt
        for i, c in enumerate(self.s.colors):
            b = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
            b.set_rgba(rgba_of(c))
            b.connect("notify::rgba", self.on_palette, i)
            self.palette_box.append(b)
        for icon, tip, fn in (("list-remove-symbolic", "Remove the last colour", self.on_palette_less),
                              ("list-add-symbolic", "Add a colour", self.on_palette_more)):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.add_css_class("flat")
            b.connect("clicked", fn)
            self.palette_box.append(b)

    def on_palette(self, b, _p, i):
        self.s.colors[i] = hex_of(b.get_rgba())
        self.changed()

    def on_palette_less(self, *_):
        if len(self.s.colors) > 1:
            self.s.colors.pop()
            self.fill_palette()
            self.changed()

    def on_palette_more(self, *_):
        if len(self.s.colors) < 12:
            self.s.colors.append(self.s.colors[len(self.s.colors) % len(self.s.colors)])
            self.fill_palette()
            self.changed()

    # -- animations ---------------------------------------------------------------
    def on_anim_toggle(self, row, _p, key):
        enabled = [k for k in self.s.enabled if k != key]
        if row.get_active():
            enabled.append(key)
        self.s.enabled = enabled
        self.changed()

    def on_open_folder(self, *_):
        Gtk.FileLauncher.new(Gio.File.new_for_path(str(ANIMATIONS_DIR))).launch(self, None, None)

    def on_reload(self, *_):
        self.load_errors = {}
        self.anims = discover(errors=self.load_errors)
        self.build()
        self.rebuild_preview()
        self.toast(f"{len(self.anims)} animations loaded")

    def on_new_animation(self, *_):
        dlg = Adw.AlertDialog(heading="New animation",
                              body="Give it a short name. A copy of the example is made in the "
                                   "animations folder for you to edit.")
        entry = Gtk.Entry(placeholder_text="e.g. robot_arm", activates_default=True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("create", "Create")
        dlg.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("create")

        def done(d, result):
            if d.choose_finish(result) != "create":
                return
            key = "".join(c if c.isalnum() else "_" for c in entry.get_text().strip().lower())
            key = key.strip("_")
            if not key:
                self.toast("Give the animation a name")
                return
            path = ANIMATIONS_DIR / f"{key}.py"
            if path.exists():
                self.toast(f"{path.name} already exists")
                return
            text = (ANIMATIONS_DIR / "_template.py").read_text()
            text = text.replace('NAME = "AI chip (example)"', f'NAME = "{key.replace("_", " ").title()}"')
            path.write_text(text)
            if key not in self.s.enabled:
                self.s.enabled = [*self.s.enabled, key]
            self.on_reload()
            self.changed()
            Gtk.FileLauncher.new(Gio.File.new_for_path(str(path))).launch(self, None, None)
            self.toast(f"Created animations/{path.name}. Apply to keep it switched on.")
        dlg.choose(self, None, done)

    # -- enable / disable ---------------------------------------------------------
    def is_enabled(self):
        return systemctl("is-enabled", SERVICE)[1] == "enabled"

    def show_state(self):
        on = self.is_enabled()
        running = systemctl("is-active", SERVICE)[1] == "active"
        self.state_row.set_title("On" if on else "Off")
        self.state_row.set_subtitle(
            f"Starts after {self.saved.idle_minutes:g} min without keyboard or mouse"
            + ("" if running or not on else " (watcher not running: press Enable again)")
            if on else "Never starts by itself. Preview on screens still works.")
        self.enable_btn.set_sensitive(not on or not running)
        self.disable_btn.set_sensitive(on or running)

    def set_enabled(self, on):
        if on:
            try:
                UNIT_DST.parent.mkdir(parents=True, exist_ok=True)
                UNIT_DST.write_text(unit_text())
            except OSError as e:
                self.toast(f"Could not install the service: {e}")
                return
            systemctl("daemon-reload")
            code, out = systemctl("enable", SERVICE)
            if code == 0:
                code, out = systemctl("restart", SERVICE)
        else:
            code, out = systemctl("disable", "--now", SERVICE)
        if code != 0:
            self.toast(f"systemctl failed: {out}")
        self.show_state()
        if code == 0:
            self.toast("Enabled: it starts after the idle time" if on else "Disabled")

    # -- running ------------------------------------------------------------------
    def on_align(self, *_):
        """Line-up pattern on the real screens; afterwards read back what it saved."""
        proc = Gio.Subprocess.new([sys.executable, str(HERE / "saver.py"), "--align"],
                                  Gio.SubprocessFlags.NONE)

        def done(p, result):
            p.wait_finish(result)
            shift = S.load(warn=lambda m: None).screen_shift
            # line-up saves straight away (Enter); keep the rest of the edits
            self.s.screen_shift = dict(shift)
            self.saved.screen_shift = dict(shift)
            self.build()
            self.rebuild_preview()
            self.update_dirty()
            self.toast(f"Screen positions: {S.write_per_screen(shift) or 'none'}")
        proc.wait_async(None, done)

    def on_run(self, *_):
        """Play now with what the window shows, applied or not."""
        try:
            S.save(self.s, PREVIEW_INI)
        except OSError as e:
            self.toast(f"Could not start the preview: {e}")
            return
        subprocess.Popen([sys.executable, str(HERE / "saver.py"), "--settings", str(PREVIEW_INI)],
                         start_new_session=True)

    def on_open_file(self, *_):
        if not S.SETTINGS_FILE.exists():
            S.save(self.saved)
        Gtk.FileLauncher.new(Gio.File.new_for_path(str(S.SETTINGS_FILE))).launch(self, None, None)

    def on_reset(self, *_):
        dlg = Adw.AlertDialog(heading="Reset to defaults?",
                              body="The window goes back to the starting settings. Nothing "
                                   "changes until you press Apply. Animation files are not "
                                   "touched.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("reset", "Reset")
        dlg.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)

        def done(d, result):
            if d.choose_finish(result) == "reset":
                self.s = S.Settings()
                self.build()
                self.rebuild_preview()
                self.update_dirty()
                self.toast("Defaults loaded: press Apply to keep them")
        dlg.choose(self, None, done)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.get_active_window() or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv[:1]))
