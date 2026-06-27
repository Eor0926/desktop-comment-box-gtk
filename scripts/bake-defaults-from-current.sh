#!/usr/bin/env bash
set -euo pipefail

SRC="$HOME/.config/desktop-comment-box-gtk/config.json"
OUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/desktop-comment-box/defaults.json"

if [ ! -f "$SRC" ]; then
  echo "No Desktop Comment Box config found: $SRC" >&2
  exit 1
fi

python3 - "$SRC" "$OUT" <<'PY'
import json, sys
from pathlib import Path
src = Path(sys.argv[1])
out = Path(sys.argv[2])
config = json.loads(src.read_text())
defaults = config.get('defaults')
if not isinstance(defaults, dict):
    raise SystemExit('No defaults object found in config.json')
keys = [
    'title', 'background', 'border', 'title_color', 'label_color', 'hover',
    'window_opacity', 'icon_size', 'width', 'height', 'show_hidden',
    'per_workspace'
]
clean = {k: defaults[k] for k in keys if k in defaults}
clean.setdefault('per_workspace', True)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(clean, indent=2) + '\n')
print(f'Wrote bundled defaults to: {out}')
PY
