# Desktop Comment Box GTK

Desktop Comment Box GTK is a Linux Mint Cinnamon utility for grouping desktop icons inside movable, resizable, Blueprint-style comment boxes.

It is a small GTK 3 desktop app, not a Cinnamon desklet. That matters because GTK can receive real file-manager drag/drop events from Nemo, while Cinnamon desklets cannot reliably receive external desktop/file-manager drops.

## Features

- Movable and resizable desktop comment boxes.
- Drag files, folders, and launchers from Nemo/Desktop into a box.
- Drag icons out of a box back to the Desktop.
- Drag icons from one box into another box.
- Move icons inside a box with grid snapping.
- Rename boxes by double-clicking the title.
- Configure appearance per box.
- Save an appearance as the default for future boxes.
- Per-box opacity/color settings.
- Autostart on login.
- Nemo action: **Create Comment Box from Selection**.
- Optional `C` shortcut through Nemo Actions.

## Requirements

Tested for Linux Mint Cinnamon with Nemo desktop icons.

Install dependencies:

```bash
sudo apt update
sudo apt install -y python3 python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 gir1.2-pango-1.0 libglib2.0-bin xdg-utils
```

Optional notifications:

```bash
sudo apt install -y libnotify-bin
```

## Install from GitHub

```bash
git clone https://github.com/YOUR_USERNAME/desktop-comment-box-gtk.git
cd desktop-comment-box-gtk
chmod +x install.sh
./install.sh
```

Run it:

```bash
desktop-comment-box &
```

Create another box:

```bash
desktop-comment-box --new &
```

Stop the app:

```bash
pkill -f desktop_comment_box.py
```

Uninstall:

```bash
./uninstall.sh
```

## Usage

### Box controls

- Move box: drag the title bar.
- Rename box: double-click the title.
- Resize box: drag a window edge/corner.
- Select box: click the title bar.
- Delete selected box: press Delete and confirm.
- Configure appearance: menu button → Configure Appearance.
- Set defaults: menu button → Configure Appearance → check **Use this appearance as defaults for new boxes**.

### Icon controls

- Add icons: drag files/folders/launchers from Desktop or Nemo into a box.
- Move inside a box: drag an icon and release it on the grid.
- Move to another box: drag the icon into another box.
- Export to Desktop: drag the icon outside all boxes and release it.

### Create a box from selected Desktop icons

The installer adds this Nemo action:

```text
Create Comment Box from Selection
```

Use it like this:

1. Select one or more files directly on `~/Desktop`.
2. Right-click one of the selected items.
3. Choose **Create Comment Box from Selection**.

The capture action is intentionally strict:

- Nothing selected: does nothing.
- `~/Desktop` itself: rejected.
- Files outside `~/Desktop`: rejected.
- Nested files inside Desktop folders: rejected.
- Mixed Desktop + non-Desktop selections: rejected.

### Optional `C` shortcut

Linux Mint's Nemo Actions app can assign a shortcut to the action.

1. Open the Mint menu.
2. Search for **Actions**.
3. Open **Actions**.
4. Go to **Layout**.
5. Select **Create Comment Box from Selection**.
6. Click **Click to add a shortcut**.
7. Press `C`.
8. Save.

Use this only as a Nemo/Desktop action shortcut, not as a global system shortcut.

## Data locations

Installed app:

```text
~/.local/share/desktop-comment-box-gtk/
```

Command wrappers:

```text
~/.local/bin/desktop-comment-box
~/.local/bin/desktop-comment-box-capture
```

Saved configuration:

```text
~/.config/desktop-comment-box-gtk/config.json
```

Box storage folders:

```text
~/.local/share/desktop-comment-box-gtk/boxes/
```

Capture log:

```text
~/.cache/desktop-comment-box-gtk/capture.log
```

## Troubleshooting

Kill all running instances:

```bash
pkill -f desktop_comment_box.py
```

Repair saved duplicate/synced box state:

```bash
desktop-comment-box --repair
```

Recover the newest hidden box folder to Desktop:

```bash
desktop-comment-box --recover-latest
```

Open hidden box storage:

```bash
nemo ~/.local/share/desktop-comment-box-gtk/boxes &
```

Read capture errors:

```bash
cat ~/.cache/desktop-comment-box-gtk/capture.log
```

## Build a release ZIP

```bash
./scripts/package.sh
```

The ZIP will be written to `dist/`.

## License

MIT. See `LICENSE`.
