# RealEarth webmod (dashboard integration)

TypeScript webui for RealEarth served by the **stock 7dtd web dashboard** (the
React SPA the dedicated server hosts at `/app` when `WebDashboardEnabled` is
true). It appears as "Overview" and "Map" items in the dashboard's left menu
plus a "RealEarth" section in Settings.

## Integration contract (stock engine, V3.1.0)

The stock webserver auto-detects a `WebMod/` folder inside any loaded mod
(`Webserver.Web.RegisterWebMods` -> `WebMod.ctor`):

- `<Mod.Path>/WebMod/` is served at `/webmods/<ModInfo Name>/`.
- If `bundle.js` and `styling.css` exist, the dashboard loads both, then reads
  `window[<ModInfo Name>]` (here `window.RealEarth`).
- The exported object shape:

```ts
{
  routes: { [routeName]: ReactComponent },   // left-menu items + mods/realearth/<routeName> routes
  settings: { [sectionTitle]: ReactComponent }, // Settings sidebar sections
  // optional: mapComponents, iconOverrides
}
```

- Components are rendered with the dashboard's own React passed as a prop
  (`{React, styled, HTTP, Table, ...}`). This webmod never imports or bundles
  React; every page uses `props.React` (createElement + hooks).

Requirement to keep in sync: `ModInfo.xml` `<Name>` ("RealEarth"),
`src/base.ts` `MOD_BASE_URL`, and the `window.RealEarth` key in `src/index.ts`.

## Layout

```text
webmod/
  tsconfig.json      strict TS; DOM lib only, no npm type packages
  src/               TypeScript sources (compiled, not shipped raw)
  styling.css        stylesheet served as the web mod's styling.css
scripts/
  build-webmod.sh    esbuild -> WebMod/bundle.js + styling.css + smoke test
  lint-webmod.sh     tsc --noEmit + oxlint (anti-slop + strict, deny warnings)
WebMod/              build output + exported pack data (git-ignored)
```

## Build / lint / export

No `package.json`/`node_modules` are tracked; tsc/esbuild/oxlint run through
`npx` with versions pinned inside the scripts (same policy as
`../zdtd-server-server/scripts/lint-webui.sh`).

```bash
make webmod-lint            # tsc --strict + oxlint, warnings fail
make webmod-export          # export demo pack into WebMod/data/demo
make webmod                 # bundle WebMod/bundle.js + copy styling.css
make package                # includes WebMod/ in dist/RealEarth/WebMod/
```

`make webmod-export PACK=<path> WEBMOD_EXPORT_NAME=<name>` exports a real pack
into `WebMod/data/<name>`; reference it in the UI as `data/<name>`.

## Manual integration test

1. On a dedicated server (web dashboard enabled), install the mod so
   `<Mods>/RealEarth/WebMod/` exists with `bundle.js`, `styling.css` and at
   least `data/demo/` (the packaged mod ships them).
2. Open the dashboard (`http://<host>:<WebDashboardPort>/app`), log in.
3. Left menu: RealEarth shows "Overview" and "Map". Settings: "RealEarth"
   section with the default pack path. `/api/mods` lists the mod with
   `web: {baseUrl: "/webmods/RealEarth/", bundle, css}`.

The demo pack ships by default; larger packs are regenerated with
`make webmod-export` (PNG mosaics, git-ignored runtime artifacts).

## Notes

- Data is served by the stock static handler (DirectAccess, no cache), so
  replacing files under `WebMod/data` applies on refresh.
- The bundle is a plain IIFE: no top-level await, no external imports, no
  CDN dependencies, so the dashboard can load it offline once assets exist.
- Out of scope for v1: globe view (see the standalone `viewer/`), stock-map
  overlays (`mapComponents`/`iconOverrides` need lon/lat <-> game-coord
  conversion), and in-browser `.rte` streaming.
