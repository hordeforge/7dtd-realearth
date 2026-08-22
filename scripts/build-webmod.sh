#!/usr/bin/env bash
# Compile the webmod TypeScript sources (webmod/src) into the WebMod bundle
# that the stock 7dtd dashboard loads as a web mod:
#
#   WebMod/bundle.js      IIFE that publishes window.RealEarth (entry index.ts)
#   WebMod/styling.css    copy of webmod/styling.css
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
out_dir="$root/WebMod"

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
