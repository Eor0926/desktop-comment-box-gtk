#!/usr/bin/env bash
set -euo pipefail
pkill -f desktop_comment_box.py >/dev/null 2>&1 || true
rm -f "$HOME/.local/bin/desktop-comment-box"
rm -f "$HOME/.local/bin/desktop-comment-box-capture"
rm -f "$HOME/.local/share/applications/desktop-comment-box.desktop"
rm -f "$HOME/.local/share/applications/desktop-comment-box-new.desktop"
rm -f "$HOME/.config/autostart/desktop-comment-box.desktop"
rm -f "$HOME/.local/share/nemo/actions/desktop-comment-box-capture.nemo_action"
rm -rf "$HOME/.local/share/desktop-comment-box-gtk"
find "$HOME/Desktop" "$HOME/.local/share/applications" -maxdepth 1 -type f -name '*desktop-comment-box-drop*.desktop' -delete 2>/dev/null || true
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
nemo -q >/dev/null 2>&1 || true
cat <<EOF2
Uninstalled the app files.
Saved settings may still exist at:
  $HOME/.config/desktop-comment-box-gtk
Remove that manually only if you do not need the saved boxes.
EOF2
