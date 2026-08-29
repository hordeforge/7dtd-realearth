# RealEarth TODO

This is the working backlog for the data pipeline, baked worlds, streamed
runtime, expanded-height support, viewer, and multiplayer model. Preserve data
provenance and distinguish prototypes from verified in-game behavior.

**Owns:** executable checkboxes. Status overview: [docs/MODIFICATIONS.md](docs/MODIFICATIONS.md). How-to: [docs/GAP_HARMONY_MODLETS.md](docs/GAP_HARMONY_MODLETS.md). Ideas: [DESIGN.md](DESIGN.md) §18. Hub: [docs/INDEX.md](docs/INDEX.md).

## Next

- [x] Prioritized implementation plan in-repo (`docs/IMPLEMENTATION_PLAN.md`)
- [x] P0–P8 offline cores: ExpandProductGuard, inject fail-closed (EngineHeight path), SessionOriginPolicy, StampSurfaceY, SessionStateStore, DensityBudget, CdnTilePolicy, AbsoluteHeightStore (SparseYScaffold removed as dead)
- [x] Offline tests: `test_phase_cores.py` + inject math; loadgen `re-phase-offline-gate`
- [x] Retarget and live-test runtime chunk terrain/density hooks against the
  supported 7DTD `Assembly-CSharp.dll` build (3.2.0 b9: heightQ=7 gen=4
  chunkIdx=2 playerTick=2 worldReady=1 bound live, `injectOk=True`; per-chunk
  inject evidence needs a connected player — [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)).
- [ ] Complete an end-to-end Streamed-mode test: tile lookup, absolute
  coordinates, local window movement, longitude wrap, save/reload, and deltas.
  (Live 3.2.0 covered: tile lookup, absolute spawn, SharedFixed, snapshot
  written + restored on restart (`Session restored absolute=(255,280)`).
  Open: window movement, wrap, save/reload with player deltas.)
- [ ] Lon/lat gaps tracked in docs/LON_LAT.md (lat-correct meters, antimeridian
  bboxes, save absolute session, geodesic / globe UX).
- [x] Validate the H500 sample before the Everest-scale expanded-height test and
  record collision, mesh, save, and reload results.
  (Live 3.2.0: H500 world loads, spawn sample gameY=500, clean soak.
  Everest-scale PASSED 2026-08-29: RealEarth_HeightTest + height_test pack,
  spawn sample gameY=7767; 6 loadgen bots joined, 28 per-chunk `Height inject`
  lines up to `maxH=8778 sessionPeak=8778` (matches pack peak), `blocks=True`,
  zero crashes. Vertical budget raised 2026-08-29: YDim 16384→32768 (engine
  packed-Y ceiling), sea anchor 100→16000 (real trench depth: -11 km → gameY
  5000), ceiling 11000→29000 (airliner cruise +12 km). Live soak at YDim=32768
  passed. TRENCH soak PASSED: synthetic trench pack at the product anchor
  (floor -11000 m ASL → spawn sample gameY=5000, seaY=16000, world loaded,
  clean soak) — below-sea depth injects live (`make height-map-trench`,
  `RE_SCENARIO_PACK=trench`). GEBCO bathymetry source added: `--source gebco
  --geotiff <GEBCO GeoTIFF>` (negative = below sea; pipeline roundtrip +
  product mapping tested). Collision/mesh record (2026-08-29): loadgen bots
  walked 77-78 steps + jumped 7-11 on the injected Everest surface
  (gameY ~4698-5333) with died=False drowns=0 - they stood on and crossed the
  real DEM without falling through. Open: summit-pixel sample; downloading a
  real GEBCO grid to build the Mariana trench pack (network/form-gated
  download); a human client for visual mesh check.)
- [x] Add a compatibility matrix for client, dedicated server, Harmony targets,
  YDim patcher, and tested operating modes ([docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)).

## Runtime and multiplayer

- [ ] Verify `SoloSlide` behavior across window shifts and antimeridian wrap.
- [ ] Verify `SharedFixed` with multiple players near window/tile boundaries and
  at maximum intended separation.
- [ ] Define authoritative persistence rules for terrain changes and player
  deltas as tiles unload and reload.
- [ ] Add failure handling for missing, corrupt, mismatched, and unavailable CDN
  tiles without silently generating incorrect terrain.
- [ ] Measure memory, chunk queues, mesh latency, and network behavior during
  sustained travel.

## Height expansion

- [ ] Audit all relevant static height assumptions described in
  [`docs/DYNAMIC_CHUNK_HEIGHT.md`](docs/DYNAMIC_CHUNK_HEIGHT.md).
- [ ] Test engine patch, backup, idempotent reapply, restore, and Steam-update
  recovery for both client and dedicated server.
- [ ] Validate physics, pathing, zombies, prefabs, weather, rendering, and saves
  above the stock height ceiling.
- [ ] Add automated inspection that refuses an unknown assembly build unless the
  operator explicitly selects a reviewed override.

## Data pipeline and realism

- [x] Add reproducible regional build manifests containing bounds, resolution,
  source URLs/versions, licenses, hashes, and processing parameters.
  (build-region writes `build.json` (schema realearth.build.v1): tool version,
  bbox, resolution, samples, source + params, input-file sha256 hashes,
  attribution; `realearth verify-build --pack` re-checks the hashes.)
- [ ] Implement or scope road, river, and settlement/prefab stamping with
  deterministic conflict rules.
- [x] Test tile seams, polar bounds, antimeridian regions, no-data DEM cells, and
  mixed source resolutions (seams/wrap already covered in test_coords,
  test_local_window, test_functional_guards; added 2026-08-29: polar-bound
  grid_lonlat, no-data cells fail closed to sea level, mixed-resolution
  sample clamp to ocean).
- [ ] Define practical regional/planet tile farm, cache, CDN, update, and storage
  plans.
- [ ] Review every distributable dataset against `ATTRIBUTION.md` before
  packaging it.

## Viewer

- [x] Add in-browser `.rte` streaming for datasets too large for one mosaic
  (decoder `viewer/src/rte.ts` + relief layer `rteLayer.ts`, native
  `DecompressionStream`; `export-viewer` ships the raw tiles; served tile
  verified end to end).
- [x] Add offline/vendor support for the Three.js dependency (vendored
  `viewer/vendor/three/` from node_modules, importmap points at it,
  `scripts/vendor-three.sh` refreshes + `make viewer-build` checks sync).
- [x] Add loading/error states, pack schema validation, and clearer source/
  resolution metadata in the UI (viewer + webmod `packMetaFrom` now reject a
  layer-less / degenerate-bbox / non-positive-dimension `viewer.json` with a
  named error instead of rendering an all-zero pack; pack info shows sources +
  notes + sea level).
- [x] Test keyboard, pointer, touch, narrow viewport, and large-pack memory use.
  (Headless-chromium smoke `make viewer-smoke`: pack parse + schema reject,
  .rte decode, relief canvas render, synthetic keyboard/pointer/touch dispatch;
  narrow-viewport and large-pack memory still need a live browser.)

## Documentation and release

- [ ] Work the priority slices in docs/GAP_HARMONY_MODLETS.md (terrain inject first,
  then travel/save, places, MP, UX); update status tags as each slice measures green.
  (2026-08-29: Slice 1 terrain truth marked measured green; slice 2/4 items with
  live evidence updated in the doc's gap table + slices. Open: biome paint,
  prefab/sleeper Y, origin-slide wrap, multi-bot distance proof.)
- [x] Reconcile status claims across `README.md`, `DESIGN.md`, and research docs
  after each live game-version validation (2026-08-29: README/DESIGN/ENGINE_LIMITATIONS/
  DYNAMIC_CHUNK_HEIGHT/realearth-surfaces updated to the 32768 vertical budget;
  GAP_HARMONY_MODLETS gap table + slices annotated with live evidence).
- [x] Add a first-time operator guide covering backup, install, verification,
  troubleshooting, rollback, and save compatibility ([docs/OPERATOR_GUIDE.md](docs/OPERATOR_GUIDE.md)).
- [x] Choose and add a code license before public distribution (MIT, [`LICENSE`](LICENSE)).
- [x] Run Python tests, multiplayer tests, build, package inspection, and a clean
  install smoke test before a release (308 pytest + 32 test-mp + make check green;
  `make package` produced `dist/RealEarth-v0.3.0.zip`; live 3.2.0 dedicated smoke PASS).

## Done criteria

A feature is complete when its coordinate/data assumptions are recorded, tests
cover deterministic logic, the target game build has been validated live,
failure and rollback behavior are documented, and any data license obligations
are satisfied.
