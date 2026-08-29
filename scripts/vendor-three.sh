#!/usr/bin/env bash
# Refresh the vendored three.js files under viewer/vendor/three from the
# pinned node_modules copy (viewer/node_modules/three), so the globe view
# works fully offline via the importmap and the committed files stay in sync
# with the pinned version in toolchain-versions.env / package-lock.
#
# Usage: bash scripts/vendor-three.sh [--check]
#   (no args)  copy three.module.js + OrbitControls.js into viewer/vendor/three
#   --check    exit 1 when the vendored files differ from node_modules (CI gate)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/viewer/node_modules/three"
DST="$ROOT/viewer/vendor/three"
CHECK=0
case "${1:-}" in
  "") ;;
  --check) CHECK=1 ;;
  -h|--help)
    echo "usage: vendor-three.sh [--check]" >&2
    exit 0
    ;;
  *)
    echo "ERROR: unknown argument '$1'" >&2
    exit 2
    ;;
esac

FILES=(
  "build/three.module.js:three.module.js"
  "examples/jsm/controls/OrbitControls.js:addons/controls/OrbitControls.js"
)
for pair in "${FILES[@]}"; do
  src="${pair%%:*}"
  rel="${pair#*:}"
  if [[ ! -f "$SRC/$src" ]]; then
    if [[ "$CHECK" == "1" ]]; then
      # node_modules absent (e.g. lint cache symlink without three): the
      # committed vendored files are authoritative, nothing to compare.
      echo "note: $SRC/$src absent; vendored copy stays as committed"
      continue
    fi
    echo "ERROR: missing $SRC/$src (run npm install in viewer/)" >&2
    exit 1
  fi
  if [[ "$CHECK" == "1" ]]; then
    if ! cmp -s "$SRC/$src" "$DST/$rel"; then
      echo "stale vendored three.js: $DST/$rel differs from node_modules (run scripts/vendor-three.sh)" >&2
      exit 1
    fi
  else
    mkdir -p "$DST/$(dirname "$rel")"
    cp -f "$SRC/$src" "$DST/$rel"
    echo "vendored $rel"
  fi
done
if [[ "$CHECK" == "0" ]]; then
  echo "OK vendor/three in sync with node_modules/three"
fi
