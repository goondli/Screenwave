# ScreenWave

A screensaver for Linux desktops that runs one marquee across one, two,
three, four or more monitors. Lines of text travel in waves from one monitor
to the next, and each wave carries an animation: neural network, circuit
board, robot march, data stream or AI chip. You can also add your own.

ScreenWave is made for Wayland, which classic screensavers such as
XScreenSaver cannot use. It is a GTK 4 app that opens one fullscreen window
per monitor and draws one shared scene, shifted by each monitor's position.
The GPU does the drawing (`Gtk.Snapshot`).

Free to use, change and share under the [MIT licence](LICENSE).

## Works with your monitors

- **Any number and arrangement.** Monitors can sit side by side or stacked
  (a laptop below an external screen, a 2×2 grid). Landscape and portrait
  both work, as do HiDPI and fractional scaling, mixed refresh rates, and
  projectors that don't report their size.
- **Choose where it plays.** Switch each monitor on or off. Monitors left
  out go black or keep showing the desktop.
- **Same real size and height.** The scene is laid out in millimetres from
  each monitor's reported size, so a 24″ screen next to 27″ ones shows
  everything at the same size. Tell it which edges are level on your desk
  (bottoms, centres or tops), or use **Line up screens**: a pattern you
  nudge with the arrow keys until the lines run straight, then Enter and
  **Apply**.

## Install

You need Python 3 with PyGObject, GTK 4 and libadwaita. Ubuntu, Fedora and
other GNOME desktops ship them; if one is missing, `install.sh` tells you
the package names.

```sh
git clone https://github.com/goondli/screenwave.git ~/screenwave
sh ~/screenwave/install.sh
```

This installs the following for the current user, without sudo:

- the **ScreenWave** app in the app grid and a launcher on the Desktop;
- the idle watcher as the systemd user service `screenwave.service`.

The folder can be anywhere. Run `install.sh` again after moving or updating
it. `sh install.sh --uninstall` removes everything except your settings.

## Using it

Open **ScreenWave** from the app grid or the Desktop.

- **Enable / Disable:** turns the automatic start after idle on and off.
- **Apply / Revert:** your changes show in the live preview at the top
  first. **Apply** saves them; **Revert** drops them.
- **Preview on screens:** plays it now with the settings shown, applied or
  not. Any key, click or mouse movement stops it.

The settings cover:

- **Monitors:** which ones it plays on.
- **Marquee text:** the lines, font, size, colours and ripple.
- **Motion:** speed, direction and the gap between waves.
- **Animations:** which ones run, their order and colours.
- **Sizes and heights:** matching sizes, which edges are level, and
  per-monitor fine-tuning.
- **When it runs:** idle time, how long it plays before fading to black,
  and a frame-rate limit.

Settings are saved in `~/.config/screenwave/settings.ini`, where every
option is explained in comments.

The idle watcher uses GNOME's idle monitor. On other desktops (KDE and
others) it polls the standard `org.freedesktop.ScreenSaver` idle time
instead. It does not start the screensaver while the screen is locked,
while an app is blocking idle (for example a video playing), or while
`~/.config/screenwave/paused` exists.

## Write your own animation

In the app, click **New animation…**. It copies `animations/_template.py`.
An animation is one Python file:

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
| `saver.py --settings file.ini` | use another settings file |
| `saver.py --align` | line-up pattern: ↑/↓ move the monitor under the mouse, Enter saves |
| `saver.py --snapshot out.png --at 8` | picture of all monitors at t = 8 s |
| `saver.py --profile` | drawing time per monitor per frame |
| `SCREENWAVE_DEBUG=1 saver.py` | log frames drawn per monitor every 2 s |

Every time the screensaver closes, it logs why: which key, click or mouse
movement, or a monitor change. When it is started by the idle watcher, find
these lines with `journalctl --user -u screenwave`.
