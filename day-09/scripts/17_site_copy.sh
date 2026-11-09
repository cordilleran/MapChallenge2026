#!/usr/bin/env bash
# Copy the public Day 9 app into the site as site/day09/ (D128, D136).
# Copies only what the public page needs: never the *_private.json cite-key file,
# never the simulated corpora. Run after 14_app_export.py (default, coarsened build).
set -euo pipefail
APP="$(cd "$(dirname "$0")/../app" && pwd)"
DEST="$(cd "$APP/../../site" && pwd)/day09"
rm -rf "$DEST"
mkdir -p "$DEST/data"
cp "$APP"/index.html "$APP"/app.js "$APP"/app.css "$APP"/core.js "$DEST/"
cp "$APP"/data/day09.json "$APP"/data/world50.json "$DEST/data/"
cp -r "$APP"/data/admin1 "$DEST/data/"
if find "$DEST" -name '*_private*' | grep -q .; then echo "private file in the site copy; stopping" >&2; exit 1; fi
du -sh "$DEST"
