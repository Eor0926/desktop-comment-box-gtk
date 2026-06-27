#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cat "$ROOT/VERSION")"
OUT_DIR="$ROOT/dist"
PKG="desktop-comment-box-gtk-v$VERSION"
rm -rf "$OUT_DIR/$PKG"
mkdir -p "$OUT_DIR/$PKG"
rsync -a \
  --exclude '.git' \
  --exclude '.github' \
  --exclude 'dist' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$ROOT/" "$OUT_DIR/$PKG/"
(
  cd "$OUT_DIR"
  rm -f "$PKG.zip"
  zip -r "$PKG.zip" "$PKG" >/dev/null
)
echo "$OUT_DIR/$PKG.zip"
