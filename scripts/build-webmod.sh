#!/usr/bin/env bash
# Compile the webmod TypeScript sources (webmod/src) into the webmod build
# bundle that is packaged as the WebMod folder loaded by the stock 7dtd
# dashboard:
#
#   webmod/build/bundle.js      IIFE that publishes window.RealEarth (entry index.ts)
#   webmod/build/styling.css    copy of webmod/styling.css
#
# The output lives inside the tracked webmod/ tree: a sibling "WebMod/" would
# collide with it on case-insensitive filesystems (macOS, Windows). The
# packaged mod folder keeps the game-required WebMod name (see package_mod.sh).
#
# esbuild is pinned by ESBUILD_VERSION (single source of truth:
# scripts/toolchain-versions.env; the repo tracks no package.json/node_modules)
# and installed from the committed lockfile by install-js-toolchain.sh, so the
# bundler binary that ships in a release is the hash-verified artifact. After
# bundling, a bun smoke test asserts the published object shape so a broken
# entry (missing route/settings keys) fails the build.
#
# Override locally: ESBUILD_VERSION=0.28.2 bash scripts/build-webmod.sh

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
out_dir="$root/webmod/build"

bash "$root/scripts/install-js-toolchain.sh" "$cache_dir" >/dev/null

mkdir -p "$out_dir"

"$cache_dir/node_modules/.bin/esbuild" "$root/webmod/src/index.ts" \
  --bundle \
  --format=iife \
  --target=es2022 \
  --minify \
  --sourcemap \
  --log-level=warning \
  --outfile="$out_dir/bundle.js"

cp "$root/webmod/styling.css" "$out_dir/styling.css"

# The single quotes are deliberate: this is a JS program passed verbatim to
# bun; letting the shell expand $-expressions here would corrupt it.
# shellcheck disable=SC2016
bun -e '
globalThis.window = globalThis;
require(process.argv[1]);
const webMod = globalThis.RealEarth;
if (webMod === undefined) {
  throw new Error("bundle did not publish window.RealEarth");
}
for (const route of ["Overview", "Map"]) {
  if (typeof webMod.routes?.[route] !== "function") {
    throw new Error(`bundle route missing or not a component: ${route}`);
  }
}
if (typeof webMod.settings?.RealEarth !== "function") {
  throw new Error("bundle settings missing or not a component: RealEarth");
}
console.log(`webmod smoke ok: routes=${Object.keys(webMod.routes).join(",")} settings=${Object.keys(webMod.settings).join(",")}`);
' "$out_dir/bundle.js"

echo "realearth: webmod bundle -> $out_dir/bundle.js (+ bundle.js.map, styling.css)"
