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
# esbuild runs through npx pinned by ESBUILD_VERSION (same convention as
# scripts/lint-webmod.sh; the repo does not track package.json/node_modules).
# After bundling, a node smoke test asserts the published object shape so a
# broken entry (missing route/settings keys) fails the build.
#
# Override locally: ESBUILD_VERSION=0.28.2 bash scripts/build-webmod.sh

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
esbuild_version="${ESBUILD_VERSION:-0.28.2}"
out_dir="$root/webmod/build"

mkdir -p "$out_dir"

npx --yes "esbuild@$esbuild_version" "$root/webmod/src/index.ts" \
  --bundle \
  --format=iife \
  --target=es2022 \
  --minify \
  --sourcemap \
  --log-level=warning \
  --outfile="$out_dir/bundle.js"

cp "$root/webmod/styling.css" "$out_dir/styling.css"

# The single quotes are deliberate: this is a JS program passed verbatim to
# node; letting the shell expand $-expressions here would corrupt it.
# shellcheck disable=SC2016
node -e '
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
