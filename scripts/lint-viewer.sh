#!/usr/bin/env bash
# Gate the map viewer TypeScript sources (viewer/src):
#   1. tsc --noEmit: the type gate (tsc --strict per viewer/tsconfig.json,
#      pinned TSC_VERSION; @types/three covers globe.ts's runtime importmap
#      import of three).
#   2. oxlint over the .ts sources with the anti-slop + strict rule set in
#      .oxlintrc.jsonc (warnings fail via --deny-warnings). The config enables
#      options.typeAware, so oxlint also runs the typescript/* type-aware
#      rules through the oxlint-tsgolint binary.
#
# tsc/oxlint/@types/three run through bunx. The pins live in
# scripts/toolchain-versions.env, the single source of truth shared by every
# build/lint script (the repo deliberately does not track
# package.json/node_modules). Override locally: TSC_VERSION=5.9.3 bash
# scripts/lint-viewer.sh
#
# Requires: bun (bunx).

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$root/scripts/toolchain-versions.env"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/realearth/oxlint-standards"
src_dir="$root/viewer/src"

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

# 1. Toolchain. The @rikalabs plugin, the vendored dmmulroy/anti-slop plugin
#    source (pinned by ANTI_SLOP_SHA; the project is vendored source, not an
#    npm package), oxlint-tsgolint (the type-aware backend), typescript,
#    @types/three (globe.ts's importmap import of three), and three itself
#    are installed into the cache; each step is a no-op when the pinned
#    version is already present. The pinned packages go in with one additive
#    `bun add` invocation: it merges pins into the cache manifest and never
#    prunes what a sibling script installed (each lint script therefore adds
#    its full set and self-heals after a sibling run).
#    @oxlint/plugins is the plugin API the anti-slop source imports; without
#    it the plugin cannot load. The same cache dir serves the webmod
#    (lint-webmod.sh).
mkdir -p "$cache_dir"
if [ ! -d "$cache_dir/anti-slop-src" ]; then
  fetch_retry "https://github.com/dmmulroy/anti-slop/archive/$ANTI_SLOP_SHA.tar.gz" \
    "$cache_dir/anti-slop.tar.gz"
  mkdir -p "$cache_dir/anti-slop-src"
  tar xzf "$cache_dir/anti-slop.tar.gz" -C "$cache_dir/anti-slop-src" --strip-components=2 "anti-slop-$ANTI_SLOP_SHA/src"
fi
# bun add resolves from its cache when warm (CI cache hit) instead of
# re-fetching on every run; cold cache fetches as usual. three is installed
# (not merely declared) so the @rikalabs/no-unlisted-external-imports rule
# sees it in the manifest dependencies while the repo itself stays free of a
# tracked package.json.
# type module: the vendored anti-slop plugin source is ESM; without the field
# the runtime reparses it with a MODULE_TYPELESS_PACKAGE_JSON warning.
[ -f "$cache_dir/package.json" ] || printf '{"type":"module"}\n' > "$cache_dir/package.json"
( cd "$cache_dir" && bun add --silent \
    "@rikalabs/oxlint-standards@$OXLINT_STANDARDS_VERSION" \
    "oxlint-tsgolint@$OXLINT_TSGOLINT_VERSION" \
    "@oxlint/plugins@$OXLINT_PLUGINS_VERSION" \
    "typescript@$TSC_VERSION" \
    "@types/three@$THREE_TYPES_VERSION" \
    "three@$THREE_VERSION" ) >/dev/null 2>&1 || {
  echo "realearth: lint-viewer: could not install the pinned lint toolchain into $cache_dir (offline?)" >&2
  exit 1
}

# 2. Type check (tsc --strict per viewer/tsconfig.json). Module resolution
#    walks up from viewer/src, so a symlink from viewer/node_modules to the
#    cache's node_modules exposes @types/three without vendoring anything.
ln -sfn "$cache_dir/node_modules" "$root/viewer/node_modules"
bunx -p "typescript@$TSC_VERSION" tsc -p "$root/viewer/tsconfig.json" --noEmit

cp "$root/.oxlintrc.jsonc" "$cache_dir/oxlintrc.jsonc"
cd "$cache_dir"
# tsgolint is not on the user's PATH; oxlint finds it via PATH lookup.
PATH="$cache_dir/node_modules/.bin:$PATH" \
  bunx "oxlint@$OXLINT_VERSION" --config oxlintrc.jsonc --deny-warnings "$src_dir"

echo "realearth: lint-viewer: tsc type-check and oxlint ok"
