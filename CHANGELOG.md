# Changelog

Notable changes to the RealEarth mod, its tile format, config surface, tools,
and viewer. Written for consumers (server admins, pack builders): each entry
says what changed for you and what to do about it.

Format follows Keep a Changelog. Versioning follows SemVer on a 0.x line:
while 0.x, breaking changes may land in minor releases; they are always listed
under Removed or Changed here. The shipped mod version lives in `ModInfo.xml`;
the tools package mirrors it in `tools/realearth/__init__.py` (`__version__`),
and the release gate requires both to match the tag (`v<version>`) and a dated
`## [x.y.z]` heading for the tagged version.

## [Unreleased]

### Added

- **Fuzz harnesses for the settlement parsers.** Seeded mutation targets cover
  `load_settlements_geojson` and the tile POI blob, asserting that malformed
  input is rejected with `ValueError` or yields only real coordinates, and that
  `decode_poi_blob(encode_poi_blob(plan))` round-trips.
- **Viewer opacity readout.** The Opacity slider now shows its value as a
  percentage next to the control; previously the handle position was the only
  feedback.
- **Webmod map zoom controls.** The Map page gained on-screen zoom in, zoom
  out, and Fit buttons over the stage, matching the standalone viewer.
- **Webmod server stats Refresh button.** The Overview stats card can be
  re-fetched without reloading the dashboard.
- **`make artifacts-status` reports backup freshness.** Age and sha256 of the
  newest archive, and whether the archive directory shares the repo disk. It
  exits nonzero when no archive exists, when the newest is older than
  `RE_BACKUP_MAX_AGE_DAYS` (default 7), or when its checksum no longer
  matches. Nothing schedules a backup, so this is the only evidence a backup
  is still good; run it after any bake you want to keep.
- **Installs publish atomically.** The install scripts build
  `Mods/RealEarth` and `GeneratedWorlds/<name>` in a sibling staging directory
  and rename it into place (`scripts/atomic_dir_swap.sh`). An install that
  fails part-way leaves the previous install exactly as it was, loadable by
  the game, instead of a half-written directory.
- **Every environment variable the scripts read is in `.env.example`.** The
  dedicated-server and load-test knobs (`RE_DEDICATED_USERDATA`, `RE_WORLD_NAME`,
  `RE_SERVER_SOAK`, `RE_SCENARIO_PACK`, `RE_VIEWER_SMOKE_PORT`, …) and the
  backup knobs (`RE_BACKUP_DIR`, `RE_SAVE_TRASH_DAYS`) were previously
  discoverable only by reading the scripts. All are optional and all have
  working defaults.

### Changed

- **A region pack rebuild now owns its `tiles/` directory.** `build_region`
  clears `tiles/` before writing the grid, so a rerun with a smaller grid (a
  narrower bbox, a coarser resolution, a smaller `tile_size`) no longer
  leaves stale tiles that the install scripts copy next to the new ones and
  that `earth.manifest.json` never described. Do not keep hand-placed tiles
  in the same directory a generated pack is written to; generate into one
  directory and install from another.
- **Installing a world no longer deletes the installed copy.**
  `install_height_pack.sh`, `install_proton.sh` and the dedicated harnesses
  rename `GeneratedWorlds/<name>` to
  `GeneratedWorlds_trash/<UTC stamp>__<name>` before writing the new world
  (`scripts/generated-world.sh`). A hand-edited installed world survives an
  upgrade. Nothing prunes `GeneratedWorlds_trash`; delete entries yourself
  once the new world is what you want, and watch the disk if you reinstall
  often.
- **A failed bake puts the previous world back.** `bake-world` and the
  generated-world path delete the partial output and rename the
  `<name>.pre-bake-<UTC stamp>` snapshot back into place before re-raising,
  so a failed bake no longer leaves a half-written world that looks finished.
  A restore that itself fails prints the path holding the last good world;
  move it back by hand.
- **The dedicated launcher no longer appends duplicate `UserOptions.ini`
  keys.** `scripts/useroptions_ini.sh` rewrites a key under `[General]` as a
  fixed point: every existing copy of the key is dropped (any case, any
  indentation, any section) and exactly one is written, so running the
  launcher twice leaves the file byte-identical to running it once. If you
  have accumulated duplicate copies, the next run removes them. Other keys,
  sections and comments are preserved in order.
- **`make package` fails instead of shipping a mod folder that loads
  nothing.** Building without `SEVENDTD_GAME_DIR` / `GAME_DIR` (no
  `RealEarth.dll`), packaging a Streamed folder with no tile pack under
  `Data/tiles`, and archiving a symlink are now errors instead of notes.
  Run `make demo` before `make package`, or set the game dir.
- **The viewer / webmod lint toolchain is installed from a committed
  lockfile.** `scripts/js-toolchain.lock` records the resolved packages with
  hashes, and `scripts/install-js-toolchain.sh` installs exactly that set
  (`bun install --frozen-lockfile`) before any lint script runs; each lint
  script no longer resolves its own pins at run time. A pin bumped in
  `scripts/toolchain-versions.env` without re-locking now fails the lint
  stage with the re-lock note instead of installing a different artifact, so
  `TSC_VERSION=... bash scripts/lint-viewer.sh` only works for a version the
  lock already contains.
- **Settlement parsers reject malformed map data instead of crashing.**
  `load_settlements_geojson` now skips features whose geometry or properties
  are not well formed (deeply nested rings, non-numeric population, non-finite
  or out-of-range coordinates) rather than raising `RecursionError`,
  `AttributeError`, or `ValueError` from inside the parse; only unparsable JSON
  raises. `decode_poi_blob` follows the same contract as `decode_tile`:
  oversized, non-UTF-8, or structurally wrong POI blobs raise `ValueError`.
- **`reinject` now reports tile-load latency and log suppression.** Tile
  load counters carry avg / last / max milliseconds per source (disk, CDN),
  and a new `suppressedLogLines(...)` line shows how many failure lines the
  per-tile / per-chunk / per-tick log budgets refused to print. A nonzero
  count means the server log understates the failure rate, not that the
  failures stopped.
- **Tile-load failures are budgeted and carry their target.** An unreadable
  tile root or a dead CDN no longer writes one ERROR per tile per miss window;
  the failures are counted instead, and each printed line names the tile path
  or CDN URL, the elapsed milliseconds, and (at Error level, for one-shot
  init and save/load paths) the exception stack on a single line.
- **A corrupt session snapshot is no longer skipped silently.**
  `SessionStateStore` names the file and its size when it cannot parse one,
  instead of leaving the world to restart at the config spawn with no trace.
- **Webmod narrow-viewport layout.** Below 860px the side panels stack under
  the map stage instead of squeezing it into a 300px column.
- **Webmod load errors** render next to the Load button that produced them,
  and the status line reads "Load failed" instead of going blank.
- **Viewer globe mode** disables Tile grid and Opacity, which have no effect on
  the sphere, and says so on hover.
- **Viewer globe mode** switches off the flat-only Streamed elevation layer
  and names the mosaic layer it falls back to, instead of quietly showing a
  different one.
- **Viewer status HUD** renders load, pack, and globe failures in the danger
  color so they read differently from routine status.
- **The C# mod DLL is now deterministic on a local build, not only in CI.**
  `DeterministicSourcePaths` was reached in CI only, through
  `ContinuousIntegrationBuild`; a maintainer's own `make build` / `make package`
  kept whatever the SDK would otherwise record. It is now set in
  `RealEarth.csproj` for every build.

### Fixed

- **`make sbom` output is now reproducible.** `scripts/sbom.py` fills the SPDX
  `creationInfo.created` field from `SOURCE_DATE_EPOCH` when it is exported,
  the same convention `scripts/package_zip.sh` already follows. Without it two
  builds of the same lockfile produced documents differing only in that
  timestamp, so a rebuild could not be compared byte-for-byte.
- **`vendor-three.sh` no longer sends you to a package manager this repo does
  not use.** Its error told you to `npm install in viewer/`; the repo tracks no
  `package.json`, and `viewer/node_modules` is a symlink the lint script
  creates. It now names the command that actually populates that path and
  sources `scripts/toolchain-versions.env` for the pinned three version.

### Fixed

- **Cross-thread state that the player tick and the console path share.**
  The Harmony bind counters read by `reinject` and the inject gate are now
  updated and read atomically, the runtime-POI tick throttle claims its slot
  with `Interlocked` instead of a check-then-decrement, and `recities here`
  restores the temporary discover radius in a `finally`.

## [0.5.1] - 2026-09-21

### Removed

- **`AbsoluteHeightStore.SetSurfaceMeters`** (world-coords wrapper). Callers
  use `SetSurfaceMetersEarth` (already-resolved Earth coords) directly.
- **`EngineHeightPolicy.ToStockByte`**. Callers use
  `HeightInjectMath.ToByteHeight(policy.MapMetersToGameY(elevM))`.

### Changed

- **Viewer lint no longer depends on an ambient ancestor `package.json`**:
  the Web-Mercator y formula in `tools/realearth/elevation.py` is unified in
  one `merc_y(lat, z)` helper (`_lonlat_to_tile`, crop `lat_to_py`).

## [0.5.0] - 2026-09-20

### Changed

- **YDim expand is runtime-only.** The Harmony runtime transpiler
  (`EngineHeightRuntimePatch=true`, default on) is now the single product
  expand path. No game DLL is ever edited on disk, so there is no
  backup/restore/dry-run step to run. Nothing to do for a normal install:
  `make install` already applies the expand at boot.

### Removed

- **Disk engine expand tooling.** `tools/engine_patcher`,
  `tools/network_protocol_inspector`, `scripts/apply_engine_expand.sh`,
  `scripts/patch_engine_height.sh`, the `make engine-expand` /
  `engine-expand-dry` / `engine-verify` / `engine-restore` / `install-full` /
  `build-npi` targets, and the CI C# analysis gate for the inspector are gone.
  If you scripted `make engine-expand`, switch to `make install` (or any
  install target): the mod hot-patches the YDim limits at boot.
- **`SharedSlide` multiplayer origin mode.** It always behaved exactly like
  `SoloSlide` (slides only when the player count is 1). Configs containing
  `SharedSlide` now load it as `SoloSlide` with no warning; use `SharedFixed`
  for co-located multiplayer combat coords.
- **`HeightCompress.Compress`** (stock-safe byte helper). Expanded compress is
  the only supported height path; no caller remained.

### Changed (internal)

- The webmod dashboard webui now re-exports the shared pack modules
  (types, coerce, lonWrap, map2d, pack) from `viewer/src` instead of keeping
  drifted copies. Pack parsing gains ordered layers, load warnings, and an
  explicit elev-raw scale fallback; no config or pack format changes.

## [0.4.0] - 2026-09-11

- **Persistence authoritative rule:** [`docs/TERRAIN_PERSISTENCE.md`](docs/TERRAIN_PERSISTENCE.md) + [`docs/INDEX.md`](docs/INDEX.md): RealEarth is stateless about terrain deltas (vanilla region files own builds); `TileStreamer` eviction drops only cached `.rte` tiles, never region/`.rte` on disk — wrap-aware (`EnableLongitudeWrap` → `Math.Min(dx, ntx - dx)`) and multi-focus.

### Added

- **City discovery persist-on-discover (gap 32 Partial):** `CityMapLabels` calls `SessionStateStore.TrySave` when a place is newly discovered so dedicated/shared session files pick up names without waiting for logout. Wire MP package sync still open; live soak open.
- **XUi lon/lat HUD (gap 31 Partial):** `Config/XUi_InGame/windows.xml` + `xui.xml` bind `_re_lon`/`_re_lat` via `{cvar(...)}` on `windowRealEarthLonLat` (toolbelt group). Packaging/install copy `Config/XUi_InGame`. Map grid still open; live soak open.
- **Sleeper Y re-pin after inject (gap 16 Partial):** `TryRepinSleeperVolumesNear` is public and also runs from `ChunkTerrainInject.OnChunkGenerated` after a successful height apply (not only after POI stamps). Decoration still open; live soak open.
- **Heat bands (gap 24 Partial):** `AltitudeClimate.HeatBand` (≥35/≥45 °C) + `buffAltitudeHeat01/02` via `AltitudeClimateTick` (`_re_heat_band`). Stock weather system still open; live soak open.
- **Trader stamp guarantee (gap 23 Partial):** `PreferTraderStamp` (default true) + `TraderPools` make metro/large_city/town stamps always pick `trader_*` (hash among traders). Quest XML / live soak still open.
- **Gamestage soft nudge (gap 22 Partial):** `Config/gamestages.xml` sets stock `difficultyBonus` 1.2→1.35 (packaging/install copy it). Spawning.xml still owns commercial/downtown maxcount; live soak open.
- **Kill-plane rescue (gap 35 Partial):** `FallSpawnRetune.TryKillPlaneRescue` snaps local player to surface+1 when Y is more than `KillPlaneDepthBlocks` (default 64) below sampled surface; gated by `KillPlaneRescue` (default true). Live soak open.
- **City discovery save (gap 32 Partial):** `discoveredCities` in `realearth.session.v1` via `CityMapLabels.ExportDiscoveredNames` / `RestoreDiscoveredNames`; WorldReady keeps names across Reset. MP sync still open.
- **Lon/lat HUD cvars (gap 31 Partial):** `LonLatHudTick` publishes `_re_lon` / `_re_lat` EntityBuffs custom vars ~1 Hz (gated by `ShowLonLatHud`, default true). Console `relonlat` / `rll` unchanged; XUi HUD/grid still open.
- **Landcover weather offset (gap 24 Partial):** `AltitudeClimate.LandcoverTempOffsetC` (desert +6 °C, snow/ice −8 °C, urban +2 °C, …) applied in `AltitudeClimateTick` via `ChunkTerrainSampler.SampleLandcover`. Stock biome weather still open; live soak open.
- **Vehicle surface snap (gap 36 Partial):** `FallSpawnRetune.TrySnapVehiclesToSurface` one-shot snaps `VehicleManager` vehicles to sampled surface+1 when Y is clearly wrong; `SnapVehicleToSurface` (default true). Deeper physics / live soak open.
- **Trader geography (gap 23 Partial):** `RuntimePoiInject` PrefabPools add stock `trader_jen`/`trader_bob` (metro), `trader_joel`/`trader_hugh` (large_city), `trader_rekt` (town) so city stamps can host traders. Quest XML / live soak still open.
- **Production FOW (gap 33 Partial):** `MapExploreRevealRadiusChunks` (default 8) uncovers map FOW around the local player without `DebugRevealFullMap`. `DebugMapRevealRadiusChunks` still wins when set. Live soak open.
- **Radiation / barren mapping (gap 25 Partial):** `LandcoverToBiomeId` / `LandcoverToBiomeName` map BARREN (code 3) to stock `wasteland` (id 8). Biomemap-only `radiated` (id 7) has no biome body/spawn; wasteland carries `buffWasteland_Hazard` and spawning.xml pressure. Live soak open.
- **Fall / spawn Y soft retune (gap 35 Partial):** `FallSpawnRetune` one-shot `SnapSpawnToSurface` (default true) snaps local player to sampled surface+1 when Y is clearly wrong; `FallDamageModifierScale` (default 0.35) scales static `EntityPlayer.FallDamageModifier` once per session. `FindSpawnPointAtXZ` already rides YDim expand. Kill-plane / live soak still open.
- **`relonlat` / `rll` console:** local XZ → Earth blocks → lon/lat degrees (optional `<x> <z>`; prints elev/hypoxia band when sampling the player). Gap 31 Partial (XUi HUD/grid still open).
- **Altitude climate (hypoxia + cold):** `AltitudeClimate` ISA lapse + lat base temp; `AltitudeClimateTick` on local player tick applies `Config/buffs.xml` hypoxia (≥2500/5500/8000 m) and cold (≤0/−20 °C) buffs. Packaging copies `buffs.xml`. Offline pins in `tests/test_altitude_climate.py`. Landcover weather and live soak still open (gap 24 Partial).
- **Spawn pressure modlet:** `Config/spawning.xml` raises commercial/downtown zombie `maxcount` for pine/burnt/desert/wasteland (Sandbox Enemy Density = Default). Animals untouched. Packaging/install scripts copy it. Live soak still open.

- Streamed-mode e2e offline tests (tests/test_streamed_e2e.py): pack manifest
  -> EarthGrid -> tile lookup -> absolute sampling (lon/lat + block),
  local-window slide incl. the antimeridian wrap, chunk sampling after slide,
  and missing-tile fail-closed (ocean, never a fake peak). Pins the offline
  half of the live Streamed chain.
- **Fail-closed build guard** for unknown `Assembly-CSharp.dll` builds (`Source/RealEarth/BuildGuard.cs`): hashes the DLL at init and compares against a reviewed allowlist (V3.2.0 b9 stock + disk-expanded + live installs). An unknown build (game update before re-verify) blocks height inject unless the operator explicitly sets `EngineHeightAllowUnknownBuild=true` (default `false` in all config JSONs). `tools/scripts/refresh_build_guard.py` regenerates the allowlist after verifying a new build. Wired at `ModApi` + `RuntimeHooks.EnforceInjectGate` (when `BuildGuard.Blocked`, forces `InjectBlocked`).
- DYNAMIC_CHUNK_HEIGHT audit: H2 updated for the hot-patch default; clarified
  that the engine's full 16×16×32768 column allocation is the RAM cost, while
  the inject writes only bedrock plug + 48-block crust + air above
  FullSolidBlockFillMaxSurface (interior untouched).
- Disk-patch lifecycle tests (tests/test_engine_expand_lifecycle.py): run the
  real EngineHeightPatcher.exe against a temp copy of the full Managed dir -
  expand, verify, Steam-update stale-marker backup refresh, restore, fresh
  re-expand, and idempotent reapply (no live install touched).
- Runtime YDim hot patch is now the **product default**
  (`EngineHeightRuntimePatch=true`): `RuntimeYDimTranspiler.cs` rewrites the
  inlined Y-bound literals (256→32768, 255→32767, 64→8192, 65536→volume bits)
  via Harmony transpilers at JIT time instead of the disk patcher. Only
  applies to a stock engine (disk-patched installs are never
  double-rewritten). **Validated live on a stock dedicated server**: 342
  method transpilers, `expanded=True allocY=29000`, H500 peak injected
  (sessionPeak=500), 0 crashes. The disk patcher stays in the repo
  (`Tools/EngineHeightPatcher.exe`, `make engine-expand`) as the fallback for
  load-order-sensitive hosts; research:
  7dtd-engine-research/docs/world/hot-patch-height.md.
- CDN tile policy test suite (tests/test_cdn_policy.py): pins the https-only
  URL building/validation contract (injection, userinfo, host-smuggling
  rejection) and the TileStreamer fetch failure contract (size caps,
  redirect-downgrade guard, fail-closed missing tile = ocean floor).
- Road/river/rail corridor stamping: `tools/realearth/corridors.py` +
  `--corridors <geojson>` on build-region burns LineString corridors into the
  landcover/population layers with deterministic conflict rules (road beats
  river = bridge; never paint open ocean; population zeroed under roads, kept
  riverside; idempotent re-stamp). 6 unit + integration tests.
- Reproducible build manifests: `build-region` writes `build.json`
  (schema realearth.build.v1) with tool version, bbox, resolution, samples,
  source + params, input-file sha256 hashes, and attribution lines; new
  `realearth verify-build --pack` re-checks the hashes against on-disk files.
- Viewer in-browser `.rte` streaming (decoder `viewer/src/rte.ts` via native
  `DecompressionStream` + relief layer `rteLayer.ts`; `export-viewer` ships the
  raw tiles; served tile verified end to end; "Streamed elevation (.rte)" layer
  option in the UI).
- Viewer headless smoke test (`make viewer-smoke`): drives the built modules
  through real chromium - pack parse + schema rejection, .rte decode, relief
  canvas render, synthetic keyboard/pointer/touch dispatch (8 checks).
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
