#!/usr/bin/env python3
"""Logicloom Screensaver: the settings window.

Every change is saved to ~/.config/logicloom-saver/settings.ini a moment
after you make it, and the live preview at the top redraws with it.
"""
import shutil
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
from saver import LayoutPreview, world_of  # noqa: E402

APP_ID = "in.maridian.LogicloomSaver.Settings"
HERE = Path(__file__).resolve().parent
SERVICE = "logicloom-saver.service"
UNIT_SRC = HERE / SERVICE
UNIT_DST = Path.home() / ".config" / "systemd" / "user" / SERVICE


def rgba_of(hex_color):
    c = Gdk.RGBA()
    c.parse(hex_color)
    return c


def hex_of(c):
    return "#{:02x}{:02x}{:02x}".format(*(round(v * 255) for v in (c.red, c.green, c.blue)))


def systemctl(*args):
    r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Logicloom Screensaver")
        self.set_default_size(820, 960)
        self.warnings = []
        self.s = S.load(warn=self.warnings.append)
        self.anims = discover()
        self.world = world_of(Gdk.Display.get_default())
        self._save_id = 0

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        run = Gtk.Button(label="Preview on screens")
        run.add_css_class("suggested-action")
        run.set_tooltip_text("Start the screensaver now on all monitors. Move the mouse to stop.")
        run.connect("clicked", self.on_run)
        header.pack_start(run)
        menu = Gio.Menu()
        menu.append("Open settings file", "win.open-file")
        menu.append("Reset to defaults…", "win.reset")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        view.add_top_bar(header)

        self.preview = LayoutPreview()
        self.preview.set_size_request(-1, 210)
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
        for w in self.warnings:
            self.toast(w)

    # -- helpers ------------------------------------------------------------
    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def changed(self, *_):
        """Called by every control: save shortly, refresh the preview now."""
        self.rebuild_preview()
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(400, self.save_now)

    def save_now(self):
        self._save_id = 0
        try:
            S.save(self.s)
        except OSError as e:
            self.toast(f"Could not save: {e}")
        return GLib.SOURCE_REMOVE

    def rebuild_preview(self):
        # quiet: the page already shows a "Not found" row for missing files
        self.preview.set_scene(Marquee(self.world, self.s.copy(), animations=self.anims, quiet=True))

    def spin(self, group, title, subtitle, key, lo, hi, step, digits=0):
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

    def combo(self, group, title, key, options):
        """options: [(value, label)]"""
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([lbl for _v, lbl in options]))
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
        missing = [k for k in self.s.enabled if k not in self.anims]
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

        # running
        g = group("When it runs")
        self.auto_row = Adw.SwitchRow(
            title="Start automatically",
            subtitle="Show the screensaver after the idle time below")
        self.auto_row.set_active(systemctl("is-enabled", SERVICE)[1] == "enabled")
        self.auto_row.connect("notify::active", self.on_auto)
        g.add(self.auto_row)
        self.spin(g, "Start after", "Minutes without keyboard or mouse", "idle_minutes",
                  0.5, 1440, 0.5, digits=1)
        self.spin(g, "Play for", "Minutes, then the screens fade to black; 0 = until you move",
                  "run_minutes", 0, 1440, 1, digits=1)
        self.color(g, "Background", "background")
        self.spin(g, "Frame rate limit", "Frames per second on fast screens; lower uses less CPU",
                  "fps", 10, 240, 6)

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
        self.anims = discover()
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
            self.s.enabled = [*self.s.enabled, key]
            self.on_reload()
            self.changed()
            Gtk.FileLauncher.new(Gio.File.new_for_path(str(path))).launch(self, None, None)
            self.toast(f"Created animations/{path.name}")
        dlg.choose(self, None, done)

    # -- running ------------------------------------------------------------------
    def on_auto(self, row, _p):
        if row.get_active():
            UNIT_DST.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(UNIT_SRC, UNIT_DST)
            systemctl("daemon-reload")
            code, out = systemctl("enable", "--now", SERVICE)
        else:
            code, out = systemctl("disable", "--now", SERVICE)
        if code != 0:
            self.toast(f"systemctl failed: {out}")

    def on_run(self, *_):
        self.save_now()
        subprocess.Popen([sys.executable, str(HERE / "saver.py")], start_new_session=True)

    def on_open_file(self, *_):
        self.save_now()
        Gtk.FileLauncher.new(Gio.File.new_for_path(str(S.SETTINGS_FILE))).launch(self, None, None)

    def on_reset(self, *_):
        dlg = Adw.AlertDialog(heading="Reset to defaults?",
                              body="All settings go back to how they started. Your animation "
                                   "files are not touched.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("reset", "Reset")
        dlg.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)

        def done(d, result):
            if d.choose_finish(result) == "reset":
                self.s = S.Settings()
                self.save_now()
                self.build()
                self.rebuild_preview()
                self.toast("Settings reset")
        dlg.choose(self, None, done)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.get_active_window() or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv[:1]))
