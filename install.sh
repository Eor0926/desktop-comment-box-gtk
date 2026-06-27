#!/usr/bin/env bash
set -euo pipefail

APP_NAME="desktop-comment-box"
CAPTURE_NAME="desktop-comment-box-capture"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/desktop-comment-box-gtk"
BIN_DIR="$HOME/.local/bin"
APP_DESKTOP_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
NEMO_ACTION_DIR="$HOME/.local/share/nemo/actions"

missing=()
command -v python3 >/dev/null 2>&1 || missing+=("python3")
command -v gio >/dev/null 2>&1 || missing+=("libglib2.0-bin")
command -v xdg-open >/dev/null 2>&1 || missing+=("xdg-utils")

if ! python3 - <<'PY' >/dev/null 2>&1
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib, Pango, GdkPixbuf
PY
then
  missing+=("python3-gi" "gir1.2-gtk-3.0" "gir1.2-gdkpixbuf-2.0" "gir1.2-pango-1.0")
fi

if [ "${#missing[@]}" -gt 0 ]; then
  echo "Missing dependencies. Install them with:"
  printf '  sudo apt install -y'
  printf ' %q' "${missing[@]}"
  printf '\n'
  exit 1
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APP_DESKTOP_DIR" "$AUTOSTART_DIR" "$NEMO_ACTION_DIR"
rm -rf "$INSTALL_DIR/desktop-comment-box"
cp -r "$SRC_DIR/desktop-comment-box" "$INSTALL_DIR/"
find "$INSTALL_DIR/desktop-comment-box" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$INSTALL_DIR/desktop-comment-box" -type f -name '*.pyc' -delete 2>/dev/null || true
chmod +x "$INSTALL_DIR/desktop-comment-box/desktop_comment_box.py"

cat > "$BIN_DIR/$APP_NAME" <<EOF2
#!/usr/bin/env bash
exec "$INSTALL_DIR/desktop-comment-box/desktop_comment_box.py" "\$@"
EOF2
chmod +x "$BIN_DIR/$APP_NAME"

cat > "$BIN_DIR/$CAPTURE_NAME" <<EOF2
#!/usr/bin/env bash
mkdir -p "\$HOME/.cache/desktop-comment-box-gtk"
{
  echo "--- \$(date -Is) ---"
  echo "argv count: \$#"
  printf '[%s]\n' "\$@"
} >> "\$HOME/.cache/desktop-comment-box-gtk/capture.log"
exec "$INSTALL_DIR/desktop-comment-box/desktop_comment_box.py" --capture-selected "\$@"
EOF2
chmod +x "$BIN_DIR/$CAPTURE_NAME"

cat > "$APP_DESKTOP_DIR/$APP_NAME.desktop" <<EOF2
[Desktop Entry]
Type=Application
Name=Desktop Comment Box
Comment=Desktop icon grouping boxes with real file drag and drop
Exec=$BIN_DIR/$APP_NAME
Icon=folder
Terminal=false
Categories=Utility;FileManager;
StartupNotify=false
EOF2

cat > "$APP_DESKTOP_DIR/$APP_NAME-new.desktop" <<EOF2
[Desktop Entry]
Type=Application
Name=New Desktop Comment Box
Comment=Create a new Desktop Comment Box
Exec=$BIN_DIR/$APP_NAME --new
Icon=folder-new
Terminal=false
Categories=Utility;FileManager;
StartupNotify=false
EOF2

cat > "$AUTOSTART_DIR/$APP_NAME.desktop" <<EOF2
[Desktop Entry]
Type=Application
Name=Desktop Comment Box
Comment=Start Desktop Comment Box on login
Exec=$BIN_DIR/$APP_NAME
Icon=folder
Terminal=false
X-GNOME-Autostart-enabled=true
StartupNotify=false
EOF2

cat > "$NEMO_ACTION_DIR/$APP_NAME-capture.nemo_action" <<EOF2
[Nemo Action]
Active=true
Name=_Create Comment Box from Selection
Comment=Move selected Desktop items into a Desktop Comment Box
Exec=$BIN_DIR/$CAPTURE_NAME %F
Icon-Name=folder-new
Selection=any
Extensions=any;
Quote=double
Terminal=false
Dependencies=$CAPTURE_NAME;
EOF2

# Remove the old fake drop launchers from early prototype builds, if present.
find "$HOME/Desktop" "$HOME/.local/share/applications" -maxdepth 1 -type f -name '*desktop-comment-box-drop*.desktop' -delete 2>/dev/null || true

update-desktop-database "$APP_DESKTOP_DIR" >/dev/null 2>&1 || true
nemo -q >/dev/null 2>&1 || true

cat <<EOF2
Installed Desktop Comment Box GTK.
Run it with: desktop-comment-box
Create a new box with: desktop-comment-box --new
Capture selected Nemo/Desktop icons with: desktop-comment-box-capture FILE...
A Nemo action was installed: Create Comment Box from Selection
It will also start automatically on login.
EOF2
