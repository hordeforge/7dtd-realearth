# RealEarth TODO

This is the working backlog for the data pipeline, baked worlds, streamed
runtime, expanded-height support, viewer, and multiplayer model. Preserve data
provenance and distinguish prototypes from verified in-game behavior.

**Owns:** executable checkboxes. Status overview: [docs/MODIFICATIONS.md](docs/MODIFICATIONS.md). How-to: [docs/GAP_HARMONY_MODLETS.md](docs/GAP_HARMONY_MODLETS.md). Ideas: [DESIGN.md](DESIGN.md) §18. Hub: [docs/INDEX.md](docs/INDEX.md).

## Next

- [x] Prioritized implementation plan in-repo (`docs/IMPLEMENTATION_PLAN.md`)
- [x] P0–P8 offline cores: ExpandProductGuard, inject fail-closed (EngineHeight path), SessionOriginPolicy, StampSurfaceY, SessionStateStore, DensityBudget, CdnTilePolicy, SparseYScaffold
- [x] Offline tests: `test_phase_cores.py` + inject math; loadgen `re-phase-offline-gate`
- [ ] Retarget and live-test runtime chunk terrain/density hooks against the
  supported 7DTD `Assembly-CSharp.dll` build.
- [ ] Complete an end-to-end Streamed-mode test: tile lookup, absolute
  coordinates, local window movement, longitude wrap, save/reload, and deltas.
- [ ] Lon/lat gaps tracked in docs/LON_LAT.md (lat-correct meters, antimeridian
  bboxes, save absolute session, geodesic / globe UX).
- [ ] Validate the H500 sample before the Everest-scale expanded-height test and
  record collision, mesh, save, and reload results.
- [ ] Add a compatibility matrix for client, dedicated server, Harmony targets,
  YDim patcher, and tested operating modes.

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

- [ ] Add reproducible regional build manifests containing bounds, resolution,
  source URLs/versions, licenses, hashes, and processing parameters.
- [ ] Implement or scope road, river, and settlement/prefab stamping with
  deterministic conflict rules.
- [ ] Test tile seams, polar bounds, antimeridian regions, no-data DEM cells, and
  mixed source resolutions.
- [ ] Define practical regional/planet tile farm, cache, CDN, update, and storage
  plans.
- [ ] Review every distributable dataset against `ATTRIBUTION.md` before
  packaging it.

## Viewer

- [ ] Add in-browser `.rte` streaming for datasets too large for one mosaic
  (the experimental decoder was removed; see CHANGELOG).
- [ ] Add offline/vendor support for the Three.js dependency.
- [ ] Add loading/error states, pack schema validation, and clearer source/
  resolution metadata in the UI.
- [ ] Test keyboard, pointer, touch, narrow viewport, and large-pack memory use.

## Documentation and release

- [ ] Work the priority slices in docs/GAP_HARMONY_MODLETS.md (terrain inject first,
  then travel/save, places, MP, UX); update status tags as each slice measures green.
- [ ] Reconcile status claims across `README.md`, `DESIGN.md`, and research docs
  after each live game-version validation.
- [ ] Add a first-time operator guide covering backup, install, verification,
  troubleshooting, rollback, and save compatibility.
- [ ] Choose and add a code license before public distribution.
- [ ] Run Python tests, multiplayer tests, build, package inspection, and a clean
  install smoke test before a release.

## Done criteria

A feature is complete when its coordinate/data assumptions are recorded, tests
cover deterministic logic, the target game build has been validated live,
failure and rollback behavior are documented, and any data license obligations
are satisfied.
