#!/usr/bin/env bash
# Refresh the vendored three.js files under viewer/vendor/three from the
# pinned node_modules copy (viewer/node_modules/three), so the globe view
# works fully offline via the importmap and the committed files stay in sync
# with the pinned version in toolchain-versions.env / js-toolchain.lock.
#
# The repo tracks no package.json: scripts/lint-viewer.sh installs the pinned
# three into a shared cache and symlinks viewer/node_modules at it, which is
# what this script reads.
#
# The committed files are third-party code shipped in every release, so their
# sha256 (pinned in toolchain-versions.env) is verified on every run. A blob
# that was hand-edited or fetched from somewhere other than the locked npm
# artifact fails here.
#
# Usage: bash scripts/vendor-three.sh [--check]
#   (no args)  copy three.module.js + OrbitControls.js into viewer/vendor/three
#   --check    exit 1 when the vendored files differ from node_modules (CI gate)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/toolchain-versions.env"
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
declare -A SHA256=(
  ["three.module.js"]="$THREE_MODULE_SHA256"
  ["addons/controls/OrbitControls.js"]="$THREE_ORBIT_CONTROLS_SHA256"
)
for pair in "${FILES[@]}"; do
  src="${pair%%:*}"
  rel="${pair#*:}"
  if [[ "$CHECK" == "1" ]]; then
    if [[ ! -f "$SRC/$src" ]]; then
      # node_modules absent (e.g. lint cache symlink without three): the
      # committed vendored files are authoritative, nothing to compare against.
      echo "note: $SRC/$src absent; vendored copy stays as committed"
    elif ! cmp -s "$SRC/$src" "$DST/$rel"; then
      echo "stale vendored three.js: $DST/$rel differs from node_modules (run scripts/vendor-three.sh)" >&2
      exit 1
    fi
  else
    if [[ ! -f "$SRC/$src" ]]; then
      echo "ERROR: missing $SRC/$src (run 'bash scripts/lint-viewer.sh' first: it installs" >&2
      echo "       the pinned three@$THREE_VERSION into the shared toolchain cache and links viewer/node_modules)" >&2
      exit 1
    fi
    mkdir -p "$DST/$(dirname "$rel")"
    cp -f "$SRC/$src" "$DST/$rel"
    echo "vendored $rel"
  fi
  if ! echo "${SHA256[$rel]}  $DST/$rel" | sha256sum -c - >/dev/null 2>&1; then
    echo "ERROR: $DST/$rel does not match the pinned sha256 (${SHA256[$rel]})" >&2
    echo "       update the THREE_*_SHA256 pins only after reviewing the new three.js release" >&2
    exit 1
  fi
done
if [[ "$CHECK" == "0" ]]; then
  echo "OK vendor/three in sync with node_modules/three"
fi
