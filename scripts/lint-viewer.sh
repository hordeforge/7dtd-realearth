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
# The pins live in scripts/toolchain-versions.env, the single source of truth
# shared by every build/lint script; the resolved artifacts are recorded (with
# hashes) in scripts/js-toolchain.lock and installed by
# scripts/install-js-toolchain.sh, which tsc runs from so the type gate uses
# the hash-verified artifact. oxlint itself is not in the lock and comes through
# bunx at the pinned version.
# Override locally: TSC_VERSION=5.9.3 bash scripts/lint-viewer.sh
#
# Requires: bun (bunx).

set -euo pipefail

usage() {
  # Header comment with the leading '# ' stripped; a fixed line range would
  # shift whenever a note is added above it.
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$root/scripts/toolchain-versions.env"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/realearth/js-toolchain"
src_dir="$root/viewer/src"

# 1. Toolchain: the @rikalabs plugin, the vendored dmmulroy/anti-slop plugin
#    source (pinned by ANTI_SLOP_SHA, the project is vendored source, not an
#    npm package), oxlint-tsgolint (the type-aware backend), typescript,
#    @types/three (globe.ts's importmap import of three), three itself and
#    vnu-jar, all installed from the committed lockfile with hash
#    verification. The same cache dir also serves build-viewer.sh,
#    build-webmod.sh, lint-webmod.sh and the HTML gate.
bash "$root/scripts/install-js-toolchain.sh" "$cache_dir" >/dev/null

# viewer/package.json declares the viewer sources' only external dependency.
# @rikalabs/no-unlisted-external-imports resolves that manifest by walking up
# from the linted file, so without it the rule reads whatever package.json
# happens to sit above the clone (on a CI runner there is none, so the gate
# passes there and fails on a developer machine) or falls back to the cache
# manifest. The declared range must match the pin, or the type gate and the
# vendored blobs would describe a different three than the one installed.
grep -q "\"three\": \"$THREE_VERSION\"" "$root/viewer/package.json" ||
  {
    echo "ERROR: viewer/package.json must declare three $THREE_VERSION (scripts/toolchain-versions.env)" >&2
    exit 1
  }

# 2. Type check (tsc --strict per viewer/tsconfig.json) with the lock-verified
#    tsc. Module resolution walks up from viewer/src, so a symlink from
#    viewer/node_modules to the cache's node_modules exposes @types/three
#    without vendoring anything.
ln -sfn "$cache_dir/node_modules" "$root/viewer/node_modules"
"$cache_dir/node_modules/.bin/tsc" -p "$root/viewer/tsconfig.json" --noEmit

cp "$root/.oxlintrc.jsonc" "$cache_dir/oxlintrc.jsonc"
cd "$cache_dir"
# tsgolint is not on the user's PATH; oxlint finds it via PATH lookup.
PATH="$cache_dir/node_modules/.bin:$PATH" \
  bunx "oxlint@$OXLINT_VERSION" --config oxlintrc.jsonc --deny-warnings "$src_dir"

echo "realearth: lint-viewer: tsc type-check and oxlint ok"
