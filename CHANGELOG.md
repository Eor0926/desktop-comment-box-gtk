## v1.4.13

- Preserves Nemo/GVFS custom icon metadata when moving files or folders between boxes or back to the Desktop.
- Fixes exported folders losing their custom icon after being dragged out of a comment box.

# Changelog

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
