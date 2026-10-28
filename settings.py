"""Logicloom Screensaver settings: ~/.config/logicloom-saver/settings.ini.

Every option is listed once in SPEC (section, default, parser, writer, help
text). The file is written from SPEC, so the settings window and hand edits
produce the same commented file. A value that cannot be read falls back to
its default with a warning on stderr: a typo never stops the screensaver.
"""
import configparser
import os
import sys
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "logicloom-saver"
SETTINGS_FILE = CONFIG_DIR / "settings.ini"
PAUSE_FILE = CONFIG_DIR / "paused"


# -- parsers / writers -------------------------------------------------------
def parse_hex(text):
    h = text.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        raise ValueError(f"not a #rrggbb colour: {text.strip()!r}")
    return "#" + h.lower()


def parse_hex_list(text):
    out = [parse_hex(c) for c in text.replace("\n", ",").split(",") if c.strip()]
    if not out:
        raise ValueError("give at least one colour")
    return out


def parse_lines(text):
    out = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not out:
        raise ValueError("give at least one line of text")
    return out


def parse_names(text):
    names = (n.strip() for n in text.replace("\n", ",").split(","))
    return list(dict.fromkeys(n for n in names if n))  # no duplicates, order kept


def ranged(cast, lo, hi):
    def parse(text):
        v = cast(text)
        if not lo <= v <= hi:
            raise ValueError(f"must be between {lo} and {hi}")
        return v
    parse.lo, parse.hi = lo, hi
    return parse


def choice(*options):
    def parse(text):
        t = text.strip().lower().replace(" ", "_")
        if t not in options:
            raise ValueError(f"use one of: {', '.join(options)}")
        return t
    parse.options = options
    return parse


def parse_yes(text):
    t = text.strip().lower()
    if t in ("yes", "true", "on", "1"):
        return True
    if t in ("no", "false", "off", "0"):
        return False
    raise ValueError("use yes or no")


def parse_per_screen(lo, hi):
    """'DP-2=12, DP-4=-3.5' -> {'DP-2': 12.0, 'DP-4': -3.5}"""
    def parse(text):
        out = {}
        for part in text.replace("\n", ",").split(","):
            if not part.strip():
                continue
            name, sep, value = part.partition("=")
            if not sep or not name.strip():
                raise ValueError(f"write it as SCREEN=number, e.g. DP-2=5 (got {part.strip()!r})")
            v = float(value)
            if not lo <= v <= hi:
                raise ValueError(f"{name.strip()} must be between {lo} and {hi}")
            out[name.strip()] = v
        return out
    return parse


def write_yes(v):
    return "yes" if v else "no"


def write_per_screen(v):
    return ", ".join(f"{k}={x:g}" for k, x in sorted(v.items()))


def write_plain(v):
    return f"{v:g}" if isinstance(v, float) else str(v)


def write_list(v):
    return ", ".join(v)


def write_lines(v):
    # configparser multi-line value: continuation lines are indented
    return "\n    ".join(v)


# key: (section, default, parse, write, help)
SPEC = {
    # [marquee]
    "lines": ("marquee", ["LOGICLOOM LLP", "ROBOTICS", "ARTIFICIAL INTELLIGENCE"],
              parse_lines, write_lines,
              "Text that travels across the screens, one wave per line, in turn.\n"
              "Put each line on its own row, indented by a few spaces."),
    "font": ("marquee", "Ubuntu Bold", str.strip, write_plain,
             "Font name and style, e.g. Ubuntu Bold, DejaVu Sans Bold, Ubuntu Condensed Bold."),
    "text_size": ("marquee", 180, ranged(int, 20, 900), write_plain,
                  "Text height in pixels."),
    "text_color": ("marquee", "#ffffff", parse_hex, write_plain, "Text colour."),
    "glow_color": ("marquee", "#4dd9ff", parse_hex, write_plain, "Glow behind the text."),
    "speed": ("marquee", 380, ranged(int, 20, 4000), write_plain,
              "How fast waves travel, in pixels per second."),
    "direction": ("marquee", "left_to_right", choice("left_to_right", "right_to_left"),
                  write_plain, "left_to_right or right_to_left."),
    "wave_height": ("marquee", 36, ranged(int, 0, 400), write_plain,
                    "How far the letters ripple up and down, in pixels. 0 = straight."),
    "lane": ("marquee", 50, ranged(int, 0, 100), write_plain,
             "Height of the text, as % of the band all screens share (0 top, 100 bottom)."),
    "wave_gap": ("marquee", 3.0, ranged(float, 0, 120), write_plain,
                 "Seconds between one wave leaving the first screen and the next arriving."),
    # [animations]
    "enabled": ("animations", ["neural", "circuit", "robots", "datastream"],
                parse_names, write_list,
                "Animations that ride along with the waves, in turn. Names are the\n"
                "file names in the animations folder, without .py."),
    "colors": ("animations", ["#4dd9ff", "#a885ff", "#6bff9e", "#ffcc4d", "#ff7359"],
               parse_hex_list, write_list, "Colours the animations draw with."),
    "order": ("animations", "in_turn", choice("in_turn", "random"), write_plain,
              "in_turn or random."),
    # [screens]
    "match_sizes": ("screens", True, parse_yes, write_yes,
                    "Show things at the same real size on every monitor, even when\n"
                    "their pixels differ (e.g. a 24\" next to 27\"s): yes / no."),
    "level": ("screens", "bottoms", choice("bottoms", "centres", "tops", "gnome_layout"),
              write_plain,
              "Which edges of the monitors are level on the desk: bottoms, centres,\n"
              "tops, or gnome_layout (the heights from GNOME's display settings).\n"
              "Text then sits at the same real height on every monitor."),
    "screen_shift": ("screens", {}, parse_per_screen(-500, 500), write_per_screen,
                     "Move a monitor's picture up (+) or down (-), in mm, so lines run\n"
                     "straight across monitors mounted at different heights.\n"
                     "e.g. DP-2=12, DP-4=-3. 'Line up screens' in the window sets this."),
    "screen_inches": ("screens", {}, parse_per_screen(5, 120), write_per_screen,
                      "Only if a monitor reports the wrong size: its diagonal in inches,\n"
                      "e.g. DP-4=23.8."),
    # [saver]
    "idle_minutes": ("saver", 5.0, ranged(float, 0.1, 1440), write_plain,
                     "Minutes without keyboard or mouse before it starts."),
    "run_minutes": ("saver", 0.0, ranged(float, 0, 1440), write_plain,
                    "Minutes it plays before the screens fade to black. 0 = until you move."),
    "background": ("saver", "#03050a", parse_hex, write_plain, "Background colour."),
    "fps": ("saver", 72, ranged(int, 10, 240), write_plain,
            "Highest frames per second on the 144 Hz screens. Lower = less CPU."),
}
SECTIONS = ["marquee", "animations", "screens", "saver"]


class Settings:
    def __init__(self, **values):
        for key, (_s, default, *_r) in SPEC.items():
            if isinstance(default, (list, dict)):
                default = type(default)(default)  # never share the default
            setattr(self, key, default)
        for key, value in values.items():
            setattr(self, key, value)

    def copy(self):
        def own(v):
            return type(v)(v) if isinstance(v, (list, dict)) else v
        return Settings(**{k: own(getattr(self, k)) for k in SPEC})


def load(path=SETTINGS_FILE, warn=None):
    """Read settings, creating the file with defaults if it is missing.
    `warn(msg)` receives every problem; by default they go to stderr."""
    warn = warn or (lambda m: print(f"logicloom-saver: {m}", file=sys.stderr))
    s = Settings()
    if not path.exists():
        try:
            save(s, path)
        except OSError as e:
            warn(f"could not create {path}: {e}")
        return s
    try:
        # errors="replace": one bad byte spoils only its own value
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        warn(f"{path} unreadable, using defaults: {e}")
        return s
    if "�" in text:
        warn(f"{path} is not UTF-8; unreadable characters were replaced")
    # Comments are only lines starting with # or ; in column 0. configparser
    # would also drop INDENTED ones, which are marquee lines like "#1 IN AI".
    text = "\n".join(ln for ln in text.splitlines() if not ln.startswith(("#", ";")))
    # strict=False: a repeated key or section keeps the last value instead of
    # throwing the whole file away
    cp = configparser.ConfigParser(interpolation=None, comment_prefixes=(), strict=False)
    try:
        cp.read_string(text)
    except configparser.Error as e:
        warn(f"{path} unreadable, using defaults: {e}")
        return s
    for section in cp.sections():
        for key, raw in cp.items(section):
            if key not in SPEC:
                warn(f"unknown setting [{section}] {key} ignored")
                continue
            try:
                setattr(s, key, SPEC[key][2](raw))
            except (ValueError, TypeError) as e:
                warn(f"{key} = {raw!r}: {e}; using {SPEC[key][1]!r}")
    return s


def render(s):
    out = ["# Logicloom Screensaver settings.",
           "# Change them in the Logicloom Screensaver window, or edit this file:",
           "# idle_minutes applies at once, the rest the next time it starts.",
           "# A value that can't be read falls back to its default.", ""]
    for section in SECTIONS:
        out.append(f"[{section}]")
        for key, (sec, _d, _p, write, help_text) in SPEC.items():
            if sec != section:
                continue
            out += [f"# {ln}" for ln in help_text.splitlines()]
            out.append(f"{key} = {write(getattr(s, key))}")
            out.append("")
    return "\n".join(out)


def save(s, path=SETTINGS_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(render(s))
    tmp.replace(path)  # atomic: the saver never reads a half-written file
