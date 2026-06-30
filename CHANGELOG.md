# Changelog

## v1.4.19

- Adds resize-to-grid cleanup behavior.
- When a box is resized smaller and an icon grid cell is fully outside the new box area, that item is moved back to the Desktop near its current screen position.
- When the resized edge lands partway through an icon tile, the box snaps outward to the next grid boundary so the icon stays enclosed.
- Box resizing now settles on desktop-style icon grid boundaries.

## v1.4.17

- Tightened icon selection and hover highlight geometry.
- Selection highlight now wraps only the icon and filename content instead of stretching through the full grid cell.
- Kept fixed grid spacing and thumbnail behavior from v1.4.16.

## v1.4.16

- Fixed tile backgrounds turning white after icons were unselected.
- Clearing selection now also clears stale hover/highlight classes.
- Added explicit transparent base styling for icon tiles to avoid GTK theme fallback backgrounds.

# Changelog

## v1.4.15

- Fixes item selection clearing when clicking blank space/header or when the box loses focus.
- Adds Ctrl-click selection toggling.
- Adds Shift-click range selection.
- Adds configurable selection highlight color in Configure Appearance.
- Makes right-click item actions respect multi-selected files where appropriate.
- Makes icon tiles fixed-size so long filenames no longer affect grid placement.
- Makes icon layout uniform by scaling thumbnails/icons into a fixed square icon area.

## v1.4.14

- Adds visible selection highlighting for items inside comment boxes.
- Adds a fuller right-click item menu with Open, Open With, Cut, Copy, Rename, Move to Desktop, Move to Trash, Open Containing Folder, and Properties.
- Adds image thumbnails for image files inside boxes and drag previews.
- Adds video thumbnail support from existing thumbnail cache, with optional generation when `ffmpegthumbnailer` is installed.

## v1.4.13

- Preserves Nemo/GVFS custom icon metadata when moving files or folders between boxes or back to the Desktop.
- Fixes exported folders losing their custom icon after being dragged out of a comment box.

## v1.4.12

- Respect custom folder icons set through Nemo/Gio metadata.
- Respect `.directory` Icon= custom folder icons where present.
- Use the same custom icon lookup for normal display icons and drag previews.

## v1.4.11

- Removed the bundled `defaults.json` file and local-default baking helper script from the public GitHub version.
- Hardcoded the finalized standard default appearance directly into the app.
- Kept per-workspace boxes enabled by default.
- Kept the hidden maximum box size at **1800×1300 px**.

## v1.4.10

- Baked user-provided default appearance into bundled defaults.
- Kept per-workspace boxes enabled by default.
- Based on v1.4.9 maximum box size behavior.

## v1.4.9

- Doubled the hidden maximum box size from **900×650 px** to **1800×1300 px**.

## v1.4.8

- Made per-workspace boxes the default for newly-created boxes.
- Removed the visible three-bar header/menu button.
- Kept right-click menu functionality on the entire title/header bar.
- Moved “Use this appearance as defaults for new boxes” into Configure Appearance.

## v1.4.7

- Added per-workspace box support.

## v1.4.6

- Stabilized icon movement with drag preview and grid commit on release.
- Made appearance changes per-box.
- Moved “Use this appearance as defaults for new boxes” into Configure Appearance.
