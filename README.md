# Desktop Comment Box GTK

Desktop Comment Box GTK creates draggable, resizable desktop icon containers for Linux Mint/Cinnamon. It is meant to behave like a desktop version of UE-style comment boxes: group files visually, drag files in and out, move icons on a grid, and capture selected desktop icons into a new box.

## Features

- Drag files/folders/launchers into a comment box.
- Drag files out of a box back to the desktop.
- Move icons inside a box with grid snapping.
- Move icons between comment boxes.
- Create a box from selected desktop icons using the Nemo action/shortcut.
- Per-box appearance settings.
- New boxes default to per-workspace behavior.
- Right-click the title/header bar to open the menu.
- Autostart on login.

## Install

```bash
sudo apt update
sudo apt install -y python3-gi gir1.2-gtk-3.0

git clone https://github.com/YOUR_USERNAME/desktop-comment-box-gtk.git
cd desktop-comment-box-gtk
chmod +x install.sh
./install.sh
desktop-comment-box &
```

Optional workspace restore helpers:

```bash
sudo apt install -y xdotool wmctrl
```

## Commands

Start:

```bash
desktop-comment-box &
```

Create a new box:

```bash
desktop-comment-box --new &
```

Kill/stop:

```bash
pkill -f desktop_comment_box.py
```

Repair old duplicate state:

```bash
desktop-comment-box --repair
```

## Capture selected desktop icons

The installer adds a Nemo action:

```text
Create Comment Box from Selection
```

Use it from the desktop context menu or assign it a shortcut in Nemo Actions. Capture only works with selected items directly inside `~/Desktop`; empty selections and mixed locations are rejected.

## Uninstall

```bash
./uninstall.sh
```


## v1.4.13 note

The hidden maximum box size is **1800×1300 px**. The standard default appearance is built into the app; no extra defaults file is needed.


### v1.4.13 note

Preserves custom folder icons when items are moved back to the Desktop.
