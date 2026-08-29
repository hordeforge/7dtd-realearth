# Changelog

Notable changes to the RealEarth mod, its tile format, config surface, tools,
and viewer. Written for consumers (server admins, pack builders): each entry
says what changed for you and what to do about it.

Format follows Keep a Changelog. Versioning follows SemVer on a 0.x line:
while 0.x, breaking changes may land in minor releases; they are always listed
under Removed or Changed here. The shipped mod version lives in `ModInfo.xml`;
the tools package mirrors it in `tools/realearth/__init__.py` (`__version__`),
and the release gate requires both to match the tag (`v<version>`).

## [Unreleased]

### Added

- Biome paint from landcover: the inject writes the per-column biome
  (`Chunk.SetBiomeId`) from the sampled landcover byte (stock biomemap ids:
  water=6, snow=1, wasteland=8, desert=5, pine_forest=3), so stock RWG biome
  noise no longer fights the injected terrain.
- Runtime prefab stamps fixed for 3.2.0: `PrefabManager` was removed, so city/
  village prefab stamps now resolve from `World.m_PrefabCache.GetPrefab` and
  place via `PrefabInstance.CopyIntoWorld` at the real surface Y (live:
  `placed 'commercial_site_02' for 'Kathmandu'` at y=4698, `farm_11` at 5333).
- SharedFixed multi-bot soak: 6 loadgen bots joined/wandered concurrently on
  the H500 world (YDim=32768), 4 players, prefab stamps, 0 crashes. An
  8-bot/400ms-ramp run hit the STOCK ConnectionManager join-churn race (no
  RealEarth frames); gentler ramp or the EfficientServer snapshot patch avoids
  it.
- GAP_HARMONY_MODLETS status reconciliation after the 3.2.0 live evidence:
  master-gap rows now carry a Status column (height inject, height APIs, byte
  lossiness, expand soak, save absolute session, fail-closed = Done; origin
  slide, region tall-Y, SharedFixed multi-bot, density stamps = Partial with
  named open items), and Slice 1 (terrain truth) is marked measured green.
- GEBCO bathymetry source: `--source gebco --geotiff <GEBCO GeoTIFF>` accepts
  real below-sea relief (negative elevation = depth below sea). The pipeline
  stores signed meters and the product sea anchor maps a -10000 m trench to
  gameY ~6000 (regression test `test_build_region_gebco_bathymetry_negative_flow`).
  Download from the GEBCO data portal (free registration).
- Trench depth proof: `realearth height-test-map --trench-game-y 5000` (and
  `make height-map-trench`) builds a synthetic trench pack at the PRODUCT sea
  anchor (floor -11000 m ASL → gameY 5000). Live dedicated soak with
  `RE_SCENARIO_PACK=trench` passed: spawn sample `gameY=5000` at `seaY=16000`,
  world loaded, clean soak; below-sea elevation injects as real diggable depth,
  no clamping.
- Full vertical relief: YDim expand raised 16384 → **32768** (the engine's
  packed game-Y ceiling), sea anchor `SeaLevelGameY` 100 → **16000**, ceiling
  `EngineMaxGameY` 11000 → **29000**. Real below-sea depth is now representable
  (trench -11 km → gameY 5000, diggable) and the airliner cruise band (+12 km →
  gameY 28000) stays under the 32767 lid. `mod_config --height-test-meta`
  raises the ceiling monotonically so a stale fixture hint cannot downgrade the
  product knob. Live dedicated soak at YDim=32768 passed (V3.2.0 b9).
- Viewer: vendored three.js r0.170.0 under `viewer/vendor/three/` (module +
  OrbitControls) so Globe mode works fully offline; the importmap resolves the
  local copy instead of the jsDelivr CDN. `scripts/vendor-three.sh` refreshes
  the vendored files from node_modules (and `--check` gates `make viewer-build`
  against drift); ATTRIBUTION updated (three.js now bundled, MIT).
- Viewer + WebMod pack schema validation: a `viewer.json` with no layers, a
  degenerate/missing bbox, or non-positive sample dimensions /
  `meters_per_block` now fails with a named error instead of silently drawing
  an all-zero pack. Viewer pack info block additionally shows data sources,
  notes, and sea level.
- `start_dedicated_minimal.sh` honors `RE_SCENARIO_PACK=everest` (was
  hardcoded to the H500 pack, silently overwriting an Everest install at every
  start); same convention as `run_dedicated_height_test.sh` and the sibling
  `7dtd-loadgen`. Live Everest soak 2026-08-29: spawn sample gameY=7767,
  28 per-chunk injects to maxH=8778 with 6 loadgen bots, zero crashes.
- `run_dedicated_height_test.sh`: `RE_SCENARIO_PACK=everest` forces the
  Everest `height_test` pack for the dedicated soak (matches the sibling
  `7dtd-loadgen` `RE_SCENARIO_PACK` convention; default stays H500).
- 3.2.0 retarget: the engine patcher now detects a Steam update/verify that
  replaced `Assembly-CSharp.dll` (marker sha no longer matches the DLL). It
  refreshes the stale `.re_stock_bak` from the current stock build before
  re-patching, so `make engine-expand` after an update converges instead of
  restoring the previous build's backup into the new game. Live dedicated
  boot on V3.2.0 (b9) binds every inject hook (see `docs/GAME_VERSION.md`).
- Deterministic release zip: `make package` now also writes
  `dist/RealEarth-v<version>.zip` through `scripts/package_zip.sh` with sorted
  entries, one fixed timestamp (`SOURCE_DATE_EPOCH`, else the commit date of
  `ModInfo.xml`), normalized permissions, and `.sha256` / `.buildinfo.txt`
  sidecars. Two builds of the same source produce identical archive bytes;
  hand-rolled zips with host mtimes are no longer part of the release path.
- Artifact durability net: `make artifacts-backup` writes a checksum-verified
  archive of worlds, region packs, the Terrarium tile cache, and viewer data;
  `make artifacts-restore ARCHIVE=path.tar.gz` restores it and refuses to
  clobber existing files unless `RE_FORCE_RESTORE=1`. New runbook:
  `docs/BACKUP_RESTORE.md`.
- Optional Terrarium DEM tile cache: set `RE_TERRARIUM_CACHE=<dir>` (or pass
  `cache_dir=` to `realearth.elevation.fetch_region_terrarium`) and every
  fetched tile is stored there and reused, so packs stay rebuildable offline
  if the remote dataset changes or disappears. Default stays uncached.

### Changed

- The dedicated height-test harness no longer deletes existing saves outright:
  old saves move to `<userdata>/Saves_trash/<utc-stamp>_<save>`, and trash
  older than `RE_SAVE_TRASH_DAYS` days (default 7) is pruned on each run.
  Runs pointed at real userdata can no longer destroy play progress.
- Dedicated launch scripts stamp log filenames with UTC time and pid
  (`server_minimal_<utc-stamp>_<pid>.txt` and friends), so two starts can no
  longer write into one file. The chosen path is echoed and written to
  `<userdata>/dedicated.logpath`: tail that file instead of a fixed name.
- Makefile and Python tools honor an exported `SEVENDTD_GAME_DIR`: it seeds
  the default `GAME_DIR` in make, while an explicit `GAME_DIR=` on the command
  line still wins; `realearth.cli`, generated-world export, and the proton
  path helpers resolve the game dir and Steam roots through the same variable.
  Install targets can no longer silently ignore the variable the scripts read.
- The packaged mod folder ships `LICENSE` next to `ModInfo.xml` (the mod is
  redistributed standalone, so the license text must travel with it), and no
  longer copies `docs/INDEX.md` into `Docs/` because its links point at
  workspace paths that do not exist inside a shipped folder. Refresh the mod
  folder contents when re-packaging an install.

### Fixed

- Map reveal state and the height-inject gate synchronize across threads,
  removing races between chunk generation and map rendering under load.
- Place names from settlement sources are normalized to NFC at C# ingestion
  and settlement files declare UTF-8 reads, fixing mojibake city map labels
  for accented names.
- External settlement population values are clamped to the int range at parse
  time, so out-of-range data cannot break label generation.
- Corrupt `.rte` compressed sections now raise `ValueError`, like every other
  malformed-tile rejection in `tools.realearth.tile_format`; previously a raw
  `zlib.error` could escape `_inflate_exact`. Callers catching `ValueError`
  need no change; code catching only `zlib.error` must catch `ValueError`.
- Viewer and webmod map controls give feedback on invalid jump-to-coords
  input and submit on Enter; globe spin/jump buttons carry state tooltips.
- Seed-generated places derive label size bands from the same population
  ladder as externally stamped settlements, so mixed worlds label
  consistently instead of sizing the two sources differently.

### Removed

- Inert placeholder configs `Config/biomes.xml` and `Config/rwgmixer.xml` are
  gone from the mod package. The game never loaded them; delete any local
  copies. Landcover and biome behavior is unchanged.

### Security

- Place names from external settlement files are stripped of Unicode control
  characters after NFC normalization (`CityMapLabels.NormalizePlaceName` and
  `tools.realearth.settlements.normalize_place_name`). Names are echoed into
  the server log, so a hostile pack could forge log lines with embedded CR/LF
  or tab characters; legitimate place names never contain control characters.

### Performance

- Chunk terrain sampling inflates each `.rte` section once and reserves the
  exact output capacity up front instead of growing the buffer during decode,
  cutting allocation cost on multi-MB elevation sections in the streaming hot
  path.
- Per-chunk reflection member lookups are memoized in the generation hook,
  removing repeated lookups per chunk.

## [0.3.0] - 2026-08-26

### Added

- Viewer globe navigation: eased fly-to jumps, `+/-` zoom buttons, idle spin
  with pause-on-interaction and a Spin toggle, and jump-to-player in both
  views (button, `P` key, `?player=lat,lon` deep link, or the optional
  polled `viewer/data/player.json` feed). Region packs are composited at 4k
  with anisotropic filtering and auto-framed when the globe opens.
- `realearth engine-audit` reads live `Assembly-CSharp.dll` metadata when
  installed with the new `audit` extra (dnfile); without it the audit falls
  back to documented engine defaults.
- `make html-lint` validates the viewer HTML and CSS through the W3C Nu Html
  Checker, and `make lint` now also runs `black --check` and `mypy` beside
  ruff. Both run in CI.

### Changed

- The web map viewer is now written in TypeScript (`viewer/src/*.ts`) instead
  of plain JavaScript (`viewer/js/*.js`). `make viewer-build` compiles it to
  the served ES modules (`viewer/js/`, now generated and gitignored), and
  `make viewer-lint` type-checks with strict tsc plus oxlint (anti-slop +
  oxlint-standards strict, type-aware). `make serve` rebuilds automatically,
  so serving the viewer needs no new steps.
- Install and dedicated-launch scripts write config through
  `realearth.mod_config` and `realearth.server_config` instead of inline
  python. Two behaviour changes follow: `make package` and Streamed installs
  now take `WorldWidth`/`WorldHeight`/`LocalWindowSize` from the pack manifest
  that was actually copied in (packaging previously hardcoded 1024x1024, wrong
  for any pack of a different size), and a serverconfig property the template
  is missing is inserted rather than skipped, so `EACEnabled`,
  `ServerVisibility` and `WebDashboardEnabled` cannot silently stop being
  forced.
- Height-pack installs now write `EngineHeightStockSafe=false`. The installer
  previously opted installs into global height compress; unexpanded engines
  are meant to hit the loud expand guard instead (see `docs/HEIGHT_LIMITS.md`).
  If you relied on StockSafe compress, set it back explicitly after install.
- Streamed installs decide `EnableLongitudeWrap` once from the final canvas
  width: on for planet-wide canvases (10M+ blocks), off otherwise, matching
  runtime behaviour. Previously streamed installs forced wrap on and only some
  regional paths turned it off afterwards.
- Dedicated-launch scripts no longer splice `$WORLD_NAME`, `$USERDATA` or
  `$MAX_PLAYERS` into a python heredoc body, where a value carrying a quote or
  a newline ran as code. Every value now arrives as argv and is written through
  an XML parser.

### Removed

- Config key `EnableGlobeMap` (`Config/realearth.json`, `realearth.mp.json`,
  `realearth.advanced_height.json`) and the unwired C# globe overlay stub it
  controlled (`Source/RealEarth/GlobeMap.cs`). It was never reachable from any
  UI. Existing config files keep loading; the runtime ignores unknown keys, so
  you can leave stale entries in place or delete them.

### Security

- Pack inputs are rejected before destructive or networked use: hostile
  manifests and pack strings fail fast instead of reaching bake, install, or
  CDN paths, and engine expand gained a drift verify so a patched assembly is
  detected before reuse.
- CDN tile reads bound the response body before buffering, and pack/world
  names containing path separators are rejected.
- See `SECURITY.md` and `docs/THREAT_MODEL.md`.

### Fixed

- Errors are no longer swallowed silently in inject hooks, tile copies,
  height smoothing, and chunk reinject: failures surface instead of leaving a
  stale mesh or silent no-op.
- Origin slides survive land-claim remap losses instead of desyncing player
  positions.
- `viewer_export.mosaic_pack` declared a return type it did not produce (it
  returned the manifest under a key typed as an array); it returns a
  `PackMosaic` named tuple now. Callers that unpacked it by key must use the
  field names.
- Atomic publish was extracted into one shared helper, and its non-atomic
  fallback no longer loses data when replace fails midway.

### Performance

- Per-tick hot paths trimmed across streamer, map reveal, and density; column
  sampling fused into single-lock lookups.

## [0.2.2] - 2026-08-23

Branding, docs alignment, and a large maintenance batch. `ModInfo.xml` was not
bumped for this tag, so a mod installed from `v0.2.2` reports version 0.2.1;
the tag content below still differs from 0.2.1 as listed.

### Added

- Threat model (`docs/THREAT_MODEL.md`) and security policy (`SECURITY.md`).
- Viewer keyboard pan/zoom and accessibility labels on both map views.

### Changed

- Tools: when `earth.manifest.json` omits `sea_level_game_y`, the default is
  now 100 (shared `DEFAULT_SEA_LEVEL_GAME_Y`), matching the C# config default;
  it was 32. Packs baked by any release always write the key, so existing
  packs are unaffected; only hand-written manifests missing the key sample
  different heights.
- Tools: the package version is single-sourced in `realearth/__init__.py` and
  resolved by hatchling at build time.

### Removed

- Config keys `MetersPerBlock` and `EngineHeightForceExpandedCompress`
  (`Config/*.json`, `RealEarthConfig.cs`). They had no effect: height is fixed
  at 1 m = 1 block on every product path. Existing config files keep loading;
  the runtime ignores unknown keys.
- Placeholder menu XML `Config/XUi_Menu/windows.xml` (never loaded by the game).
- Experimental browser `.rte` decoder stub `viewer/js/rte.js`. Nothing
  imported it.
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
  least privilege.

### Fixed

- Errors are no longer swallowed silently across tick, save, fetch, and bake
  paths (runtime hooks, session store, tile fetch, bake-world).
- Engine expand is re-run safe (late backup plus marker healing); a second run
  detects an already-expanded assembly instead of double-patching.
- Tile miss cache is bounded; failed publish no longer leaves a temp file.

### Performance

- Hot-path reflection cached; streaming and pipeline throughput improved.
- Urban edge radius uses scanline flood fill instead of per-pixel search.

## [0.2.1] - 2026-08-22

First tagged release.

### Added

- RealEarth mod for 7 Days to Die V3.2.0 (Henpocalypse): streamed `.rte` tiles
  with Harmony height inject, longitude wrap, multiplayer origin modes
  (SoloSlide / SharedFixed), and city map labels.
- RealEarth YDim expand tools (`Tools/` engine patcher) for tall columns;
  product path for real meters (1 m = 1 block). Stock fallback stays ~250.
- Offline Python pipeline (`realearth-tools`): region building from Copernicus /
  Terrarium-class DEM sources, density/cities stamping, `.rte` v1 tile format
  with manifest, demo region generator, baked-world export.
- Web dashboard webmod and flat + globe map viewer with lint gates in CI.
