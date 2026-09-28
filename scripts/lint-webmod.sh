#!/usr/bin/env bash
# Gate the webmod TypeScript sources (webmod/src):
#   1. tsc --noEmit: the type gate (tsc --strict per webmod/tsconfig.json,
#      pinned TSC_VERSION).
#   2. oxlint over the .ts sources with the anti-slop + strict rule set in
#      .oxlintrc.webmod.jsonc (warnings fail via --deny-warnings). The config
#      enables options.typeAware, so oxlint also runs the typescript/*
#      type-aware rules through the oxlint-tsgolint binary.
#
# The pins live in scripts/toolchain-versions.env, the single source of truth
# shared by every build/lint script; the resolved artifacts are recorded (with
# hashes) in scripts/js-toolchain.lock and installed by
# scripts/install-js-toolchain.sh, which tsc runs from so the type gate uses
# the hash-verified artifact. oxlint itself is not in the lock and comes through
# bunx at the pinned version.
# Override locally: TSC_VERSION=5.9.3 bash scripts/lint-webmod.sh
#
# Requires: bun (bunx), python3 (already a make check requirement).

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
src_dir="$root/webmod/src"

# 1. Toolchain: typescript, the @rikalabs plugin, the vendored dmmulroy/anti-slop
#    plugin source (pinned by ANTI_SLOP_SHA; the project is vendored source, not
#    an npm package) and oxlint-tsgolint (the type-aware backend) come from the
#    shared cache, installed from the committed lockfile with hash
#    verification. The same cache dir also serves build-viewer.sh,
#    build-webmod.sh, lint-viewer.sh and lint-html.sh.
bash "$root/scripts/install-js-toolchain.sh" "$cache_dir" >/dev/null

# 2. Type check (tsc --strict per webmod/tsconfig.json).
"$cache_dir/node_modules/.bin/tsc" -p "$root/webmod/tsconfig.json" --noEmit

# 3. Lint the sources with oxlint, which runs next to the installed plugins
#    because jsPlugins resolve relative to the config file's directory; a copy
#    of the config is placed there each run.
cp "$root/.oxlintrc.webmod.jsonc" "$cache_dir/oxlintrc.webmod.jsonc"
cd "$cache_dir"
# tsgolint is not on the user's PATH; oxlint finds it via PATH lookup.
PATH="$cache_dir/node_modules/.bin:$PATH" \
  bunx "oxlint@$OXLINT_VERSION" --config oxlintrc.webmod.jsonc --deny-warnings "$src_dir"

echo "realearth: lint-webmod: tsc type-check and oxlint ok"
