# Changelog

Notable changes to the RealEarth mod, its tile format, config surface, tools,
and viewer. Written for consumers (server admins, pack builders): each entry
says what changed for you and what to do about it.

Format follows Keep a Changelog. Versioning follows SemVer on a 0.x line:
while 0.x, breaking changes may land in minor releases; they are always listed
under Removed or Changed here. The shipped mod version lives in `ModInfo.xml`;
tags are `v<version>`.

## [Unreleased]

### Added

- Viewer globe navigation: eased fly-to jumps, `+/−` zoom buttons, idle spin
  with pause-on-interaction and a Spin toggle, and jump-to-player in both
  views (button, `P` key, `?player=lat,lon` deep link, or the optional
  polled `viewer/data/player.json` feed). Region packs are composited at 4k
  with anisotropic filtering and auto-framed when the globe opens.

### Changed

- The web map viewer is now written in TypeScript (`viewer/src/*.ts`) instead
  of plain JavaScript (`viewer/js/*.js`). `make viewer-build` compiles it to
  the served ES modules (`viewer/js/`, now generated and gitignored), and
  `make viewer-lint` type-checks with strict tsc plus oxlint (anti-slop +
  oxlint-standards strict, type-aware). `make serve` rebuilds automatically,
  so serving the viewer needs no new steps.

### Removed

- Config keys `MetersPerBlock` and `EngineHeightForceExpandedCompress`
  (`Config/realearth.json`, `realearth.mp.json`,
  `realearth.advanced_height.json`). They had no effect: height is fixed at
  1 m = 1 block on every product path. Existing config files keep loading;
  the runtime ignores unknown keys, so you can leave stale entries in place
  or delete them.
- Placeholder menu XML `Config/XUi_Menu/windows.xml` (never loaded by the game).
- Experimental browser `.rte` decoder stub `viewer/js/rte.js`. It was never
  wired into the viewer UI; nothing imports it.
- Unused pipeline helpers (`coords.tile_origin_block`,
  `coords.lonlat_bbox_to_tiles`, `coords.meters_per_degree_*`, GeoTIFF loader
  remnants, ttw version reader, settlement stamp plan).

### Security

- `.rte` decoding rejects hostile input before allocating, in both the C#
  runtime (`Source/RealEarth/RteTile.cs`) and the Python pipeline
  (`tools/realearth/tile_format.py`): out-of-range tile dimensions, section
  lengths beyond the buffer, decompression bombs, and size mismatches now fail
  fast instead of trusting CDN or pack data.
- Example dedicated configs ship telnet off (read the log file instead);
  scripts and docs use `$HOME` instead of hardcoded user paths; CI runs with
  least privilege. See `SECURITY.md` and `docs/THREAT_MODEL.md`.

### Fixed

- Errors are no longer swallowed silently across tick, save, fetch, and bake
  paths (runtime hooks, session store, tile fetch, bake-world).
- Tile miss cache is bounded; failed publish no longer leaves a temp file.
- Engine expand is re-run safe (late backup plus marker healing); a second run
  detects an already-expanded assembly instead of double-patching.

### Changed

- Tools only: when `earth.manifest.json` omits `sea_level_game_y`, the default
  is now 100 (shared `DEFAULT_SEA_LEVEL_GAME_Y`), matching the C# config
  default; it was 32. Packs baked by any release always write the key, so
  existing packs are unaffected; only hand-written manifests missing the key
  sample different heights.

### Performance

- Hot-path reflection cached; streaming and pipeline throughput improved.
- Urban edge radius uses scanline flood fill instead of per-pixel search.

### Added

- Threat model (`docs/THREAT_MODEL.md`) and security policy (`SECURITY.md`).

## [0.2.1] - 2026-08-22

First tagged release.

### Added

- RealEarth mod for 7 Days to Die V3.1.0 (Henpocalypse): streamed `.rte` tiles
  with Harmony height inject, longitude wrap, multiplayer origin modes
  (SoloSlide / SharedFixed), and city map labels.
- RealEarth YDim expand tools (`Tools/` engine patcher) for tall columns;
  product path for real meters (1 m = 1 block). Stock fallback stays ~250.
- Offline Python pipeline (`realearth-tools`): region building from Copernicus /
  Terrarium-class DEM sources, density/cities stamping, `.rte` v1 tile format
  with manifest, demo region generator, baked-world export.
- Web dashboard webmod and flat + globe map viewer with lint gates in CI.
