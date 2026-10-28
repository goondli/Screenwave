#!/bin/sh
# Installs the ScreenWave for this user (no sudo), from wherever
# this folder is:
#   - the settings window in the app grid, and a launcher icon on the Desktop
#   - the idle watcher as a systemd user service (enabled and started)
# Run again any time (e.g. after moving the folder or updating); it only
# overwrites its own files. Remove everything with:  sh install.sh --uninstall
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ID=io.github.goondli.ScreenWave
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
UNITS="$HOME/.config/systemd/user"
DESKTOP=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")

if [ "${1:-}" = "--uninstall" ]; then
    systemctl --user disable --now screenwave.service 2>/dev/null || true
    rm -f "$UNITS/screenwave.service" "$APPS/$ID.desktop" "$ICONS/$ID.svg" \
          "$DESKTOP/ScreenWave.desktop"
    systemctl --user daemon-reload 2>/dev/null || true
    echo "Uninstalled. Your settings stay in ~/.config/screenwave; delete that folder too if you like."
    exit 0
fi

# Everything it needs ships with GNOME desktops; say what is missing.
if ! python3 - <<'EOF' 2>/dev/null
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
EOF
then
    echo "Missing Python GTK 4 / libadwaita. On Ubuntu or Debian:"
    echo "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"
    echo "On Fedora:  sudo dnf install python3-gobject gtk4 libadwaita"
    exit 1
fi

mkdir -p "$APPS" "$ICONS" "$UNITS" "$DESKTOP"

# earlier versions were called "Logicloom Screensaver": remove that install
if [ -e "$UNITS/logicloom-saver.service" ]; then
    systemctl --user disable --now logicloom-saver.service 2>/dev/null || true
    rm -f "$UNITS/logicloom-saver.service"
fi
rm -f "$APPS/in.maridian.LogicloomSaver.Settings.desktop" \
      "$ICONS/in.maridian.LogicloomSaver.Settings.svg" "$DESKTOP/Logicloom Screensaver.desktop"

cp "$HERE/icon.svg" "$ICONS/$ID.svg"

# Desktop Entry paths: quote for spaces, double % (the spec's escape)
Q=$(printf '%s' "$HERE" | sed 's/%/%%/g; s/\\/\\\\/g; s/"/\\"/g; s/`/\\`/g; s/\$/\\$/g')
cat > "$APPS/$ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ScreenWave
Comment=Marquee screensaver across your monitors - settings and preview
Exec=/usr/bin/python3 "$Q/settings_gui.py"
Icon=$ID
Terminal=false
Categories=Settings;DesktopSettings;
Keywords=screensaver;marquee;monitors;multi-monitor;
StartupNotify=true
Actions=start;

[Desktop Action start]
Name=Start screensaver now
Exec=/usr/bin/python3 "$Q/saver.py"
EOF

cp "$APPS/$ID.desktop" "$DESKTOP/ScreenWave.desktop"
chmod +x "$DESKTOP/ScreenWave.desktop" "$HERE/saver.py" "$HERE/settings_gui.py" "$HERE/idle_watch.py"
# lets the Desktop Icons extension launch it without the "untrusted" prompt
gio set "$DESKTOP/ScreenWave.desktop" metadata::trusted true 2>/dev/null || true

# the service points at this folder (systemd: % must be doubled)
U=$(printf '%s' "$HERE" | sed 's/%/%%/g; s/[&|\]/\\&/g')
sed "s|@HERE@|$U|g" "$HERE/screenwave.service.in" > "$UNITS/screenwave.service"
systemctl --user daemon-reload
systemctl --user enable screenwave.service
# restart, not just start: a re-run must pick up new idle_watch.py code
systemctl --user restart screenwave.service

update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Installed. Open 'ScreenWave' from the Desktop or the app grid."
