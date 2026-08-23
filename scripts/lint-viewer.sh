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
# node_modules tracked; same policy as ../zdtd-server/scripts/lint-webui.sh).
# Override locally: OXLINT_VERSION=1.79.0 OXLINT_STANDARDS_VERSION=0.8.1 \
#   bash scripts/lint-viewer.sh
#
# Requires: node/npm (npx).

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
oxlint_version="${OXLINT_VERSION:-1.79.0}"
oxlint_standards_version="${OXLINT_STANDARDS_VERSION:-0.8.1}"
oxlint_plugins_version="${OXLINT_PLUGINS_VERSION:-1.78.0}"
anti_slop_sha="${ANTI_SLOP_SHA:-6d538555cb151d4121ed51a27db81890eacf8ae9}"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/realearth/oxlint-standards"
js_dir="$root/viewer/js"

# GitHub archive downloads fail intermittently; retry with deterministic
# backoff so a transient 5xx does not turn the lint stage red.
fetch_retry() {
  local url="$1" out="$2" attempt delay
  for attempt in 1 2 3; do
    if curl -fsSL "$url" -o "$out"; then
      return 0
    fi
    rm -f "$out"
    delay=$((attempt * 2))
    echo "realearth: lint-viewer: fetch failed (attempt $attempt), retrying in ${delay}s" >&2
    sleep "$delay"
  done
  return 1
}

mkdir -p "$cache_dir"
if [ ! -d "$cache_dir/anti-slop-src" ]; then
  fetch_retry "https://github.com/dmmulroy/anti-slop/archive/$anti_slop_sha.tar.gz" \
    "$cache_dir/anti-slop.tar.gz"
  mkdir -p "$cache_dir/anti-slop-src"
  tar xzf "$cache_dir/anti-slop.tar.gz" -C "$cache_dir/anti-slop-src" --strip-components=2 "anti-slop-$anti_slop_sha/src"
fi
# prefer-offline: reuse the npm cache when warm (CI cache hit) instead of
# re-resolving against the registry on every run; cold cache fetches as usual.
npm install --prefix "$cache_dir" --prefer-offline --no-audit --no-fund --no-save --no-package-lock \
  "@rikalabs/oxlint-standards@$oxlint_standards_version" \
  "@oxlint/plugins@$oxlint_plugins_version" >/dev/null 2>&1 || {
  echo "realearth: lint-viewer: could not install @rikalabs/oxlint-standards@$oxlint_standards_version + @oxlint/plugins@$oxlint_plugins_version into $cache_dir (offline?)" >&2
  exit 1
}
cp "$root/.oxlintrc.jsonc" "$cache_dir/oxlintrc.jsonc"
cd "$cache_dir"
npx --yes "oxlint@$oxlint_version" --config oxlintrc.jsonc --deny-warnings "$js_dir"
echo "realearth: lint-viewer: oxlint ok"
