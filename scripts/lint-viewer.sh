#!/usr/bin/env bash
# Lint the web map viewer JavaScript (viewer/js/*.js) with oxlint against the
# anti-slop + strict rule set in .oxlintrc.jsonc (warnings fail via
# --deny-warnings). Part of `make check` (target: viewer-lint).
#
# The @rikalabs plugin is fetched into the cache (no-op when the pinned version
# is already present) and oxlint runs next to it because jsPlugins resolve
# relative to the config file's directory; a copy of the config is placed there
# each run.
#
# Versions live here as the single source of truth (no package.json /
# node_modules tracked; same policy as ../zdtd/scripts/lint-webui.sh).
# Override locally: OXLINT_VERSION=1.79.0 OXLINT_STANDARDS_VERSION=0.8.1 \
#   bash scripts/lint-viewer.sh
#
# Requires: node/npm (npx).

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
oxlint_version="${OXLINT_VERSION:-1.79.0}"
oxlint_standards_version="${OXLINT_STANDARDS_VERSION:-0.8.1}"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/realearth/oxlint-standards"
js_dir="$root/viewer/js"

mkdir -p "$cache_dir"
npm install --prefix "$cache_dir" --no-audit --no-fund --no-save --no-package-lock \
  "@rikalabs/oxlint-standards@$oxlint_standards_version" >/dev/null 2>&1 || {
  echo "realearth: lint-viewer: could not install @rikalabs/oxlint-standards@$oxlint_standards_version into $cache_dir (offline?)" >&2
  exit 1
}
cp "$root/.oxlintrc.jsonc" "$cache_dir/oxlintrc.jsonc"
cd "$cache_dir"
npx --yes "oxlint@$oxlint_version" --config oxlintrc.jsonc --deny-warnings "$js_dir"
echo "realearth: lint-viewer: oxlint ok"
