# 3-screens: Logicloom Screensaver

A screensaver for GNOME on Wayland that runs one marquee across several
monitors. Lines of text ("LOGICLOOM LLP", "ROBOTICS", "ARTIFICIAL
INTELLIGENCE") travel in waves from one monitor to the next, and each wave
carries a robotics or AI animation.

Ubuntu 26.04 (GNOME 50) has no X11 session, so classic screensavers such as
XScreenSaver cannot run. This one is a GTK 4 app. It opens one fullscreen
window per monitor and draws one shared scene, shifted by each monitor's
position. Drawing goes through `Gtk.Snapshot`, so the GPU renders it.

## Features

- **Same real size and height on every monitor.** The scene is laid out in
  millimetres, using each monitor's reported size. A 24″ screen next to 27″
  screens is zoomed to match. You choose which edges of the monitors are
  level on the desk (bottoms, centres or tops). **Line up screens** shows a
  pattern you can fine-tune with the arrow keys.
- **Animations as plug-ins:** neural network, circuit board, robot march,
  data stream and AI chip. Each is one file in `animations/`.
- **Settings window** (libadwaita) with a live preview. You can change:
  - **Text:** lines, font, size and colours.
  - **Motion:** ripple, speed, direction and gap between waves.
  - **Animations:** which ones run, their order and colours.
  - **When it runs:** idle time, how long it plays, and a frame-rate limit.
- **Idle watcher.** It uses GNOME's own idle monitor. It does not start
  while the screen is locked, while an app is blocking idle (for example a
  video playing), or while `~/.config/logicloom-saver/paused` exists.

Any key, click, scroll or mouse movement closes the screensaver. Each time
it closes, it logs the reason.

## Install

Needs Python 3 with PyGObject, GTK 4 and libadwaita, which ship with
Ubuntu's desktop.

```sh
git clone https://github.com/goondli/3-screens.git ~/logicloom-saver
sh ~/logicloom-saver/install.sh
```

This installs the following for the current user, without sudo:

- the **Logicloom Screensaver** app and a Desktop launcher;
- the idle watcher as the systemd user service `logicloom-saver.service`.

The service expects the folder at `~/logicloom-saver`.

Settings live in `~/.config/logicloom-saver/settings.ini`. The settings
window writes this file, and every option in it is explained in comments.

## Write your own animation

In the settings window, click **New animation…**. It copies
`animations/_template.py`. An animation is one Python file:

```python
NAME = "My animation"
REACH = 500                      # px drawn beyond the text, each side

def setup(wave):                 # once per wave: pick random layout here
    wave.data.size = wave.rng.uniform(40, 80)

def draw(pen, wave):             # every frame, once per monitor
    pen.glow(wave.ahead(200), wave.y, wave.data.size, wave.color(0))
```

`kit.py` lists everything `pen` can draw and everything `wave` provides.
`draw()` must depend only on `wave.t` and what `setup()` stored, because
each monitor calls it separately for the same moment.

To check an animation without covering your screens:

```sh
python3 saver.py --snapshot out.png --only my_animation --at 8
python3 saver.py --profile --only my_animation
```

## Command line

| Command | What it does |
|---|---|
| `saver.py` | run until input |
| `saver.py --duration 30` | run for 30 seconds |
| `saver.py --align` | line-up pattern: ↑/↓ move the screen under the mouse, Enter saves |
| `saver.py --snapshot out.png --at 8` | picture of all monitors at t = 8 s |
| `saver.py --profile` | drawing time per monitor per frame |
| `LOGICLOOM_DEBUG=1 saver.py` | log frames drawn per monitor every 2 s |
