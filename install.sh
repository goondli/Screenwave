#!/bin/sh
# Installs the Logicloom Screensaver for this user (no sudo):
#   - the settings window in the app grid, and a launcher icon on the Desktop
#   - the idle watcher as a systemd user service (started and enabled)
# Run again any time; it only overwrites its own files.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ID=in.maridian.LogicloomSaver.Settings
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
UNITS="$HOME/.config/systemd/user"
DESKTOP=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")

mkdir -p "$APPS" "$ICONS" "$UNITS" "$DESKTOP"
cp "$HERE/icon.svg" "$ICONS/$ID.svg"

cat > "$APPS/$ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Logicloom Screensaver
Comment=Marquee screensaver across all monitors - settings and preview
Exec=/usr/bin/python3 $HERE/settings_gui.py
Icon=$ID
Terminal=false
Categories=Settings;DesktopSettings;
Keywords=screensaver;marquee;logicloom;
StartupNotify=true
Actions=start;

[Desktop Action start]
Name=Start screensaver now
Exec=/usr/bin/python3 $HERE/saver.py
EOF

cp "$APPS/$ID.desktop" "$DESKTOP/Logicloom Screensaver.desktop"
chmod +x "$DESKTOP/Logicloom Screensaver.desktop" "$HERE/saver.py" "$HERE/settings_gui.py" "$HERE/idle_watch.py"
# lets the Desktop Icons extension launch it without the "untrusted" prompt
gio set "$DESKTOP/Logicloom Screensaver.desktop" metadata::trusted true 2>/dev/null || true

cp "$HERE/logicloom-saver.service" "$UNITS/"
systemctl --user daemon-reload
systemctl --user enable --now logicloom-saver.service

update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Installed. Open 'Logicloom Screensaver' from the Desktop or the app grid."
