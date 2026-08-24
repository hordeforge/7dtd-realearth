# RealEarth prioritized implementation plan

**Owns:** P0-P8 order, outcomes, dependencies, isolation gates.  
**Not:** Done/Partial tables ([MODIFICATIONS](MODIFICATIONS.md)), gap how-to ([GAP_HARMONY_MODLETS](GAP_HARMONY_MODLETS.md)), tickets ([TODO](../TODO.md)).  
**Hub:** [INDEX](INDEX.md).

**Isolation:** pure height/sample/session math unit-tested offline (Python mirrors + C# net48 build). Live dedicated soak via loadgen (`7dtd-loadgen` RealEarth scenarios) is optional evidence for most tranches; **live inject/MP is not Done without dedicated evidence**.

---

## Priority order (P0-P8)

| Pri | Layer | Outcome | Dependencies | Isolation / test |
|---:|---|---|---|---|
| **P0** | A Binary | Expand correct on client+dedicated; audit/refuse stock when product path demands 1:1 | None | `make engine-expand-dry`, `engine-audit`; expand scripts |
| **P1** | B Inject | Live height queries + GenerateTerrain rewrite DEM; fail-closed missing tiles; patch stats | P0 for tall peaks | Unit: `HeightInjectMath` / sample policy; C# build; loadgen self-test gates |
| **P2** | C Stream | SoloSlide proof, tile bubble, no silent fake DEM | P1 | Session fold unit tests; offline streamer logic |
| **P3** | E Density | Stamps + biome on real surface Y | P1 | Pipeline density tests; stamp Y = sample height |
| **P4** | F Persist | Save absolute origin + build deltas | P2 | Save-format design + unit serialize |
| **P5** | F MP | SharedFixed co-located proof | P1-P2 | loadgen `re-h500-mp-sharedfixed` live |
| **P6** | G Budgets | Density/sim caps under load | P3 | APM + loadgen cohort stats |
| **P7** | D Data | Planet farm + CDN fail-closed | P2 | Manifest/CDN unit + offline CDN mock |
| **P8** | Later | Sparse Y, roads, climate, globe XUi | P1-P6 | Separate designs |

---

## Layer checklist (all modification classes)

### A Binary / install
- YDim expand, layers, Y-bound IL
- Client + dedicated parity
- Backup / re-apply after Steam Verify
- `.7rg` tall-Y validation (**Needed**, with P0/P1 soak)

### B Harmony / inject
- Height query override (all concrete APIs)
- GenerateTerrain postfix inject
- Chunk index / ensure tiles
- Fail-closed missing tiles + counters (**this tranche**)
- Inject patch bind stats (**this tranche**)
- Biome paint, POI/sleeper Y, light/stability (after P1)

### C Coordinate / stream
- EarthCoords, WorldSession, TileStreamer
- SoloSlide / SharedFixed
- Lon wrap, regional fold ([LON_LAT](LON_LAT.md))

### D Data pipeline
- `.rte`, bake-world, manifests, GHSL/DEM ingest
- Edge radii from density ([CITY_MAP_LABELS](CITY_MAP_LABELS.md))

### E Population / settlements
- Density stamps, city labels (done scaffold), surface Y stamps (P3)

### F Multiplayer / persistence
- Shared origin, deltas, save session (P4-P5)

### G Content / UX / budgets
- XML gamestages, FOW production, globe XUi, entity caps (P6+)

### H Ops
- Compat matrix, retarget checklist, loadgen RealEarth scenarios

---

## Shipped offline cores (P0-P8)

| Pri | Module | Offline test |
|---:|---|---|
| P0 | `ExpandProductGuard.cs` | `test_phase_cores.py::test_p0_*` |
| P1 | `HeightInjectMath`, `TileSamplePolicy`, EngineHeightMod wiring | `test_height_inject_math.py`, `test_p1_*` |
| P2 | `SessionOriginPolicy` + WorldSession wire | `test_p2_*` |
| P3 | `StampSurfaceY` + `stamp_prefabs_from_density` uses int32 surface Y (not uint8) | `test_stamp_prefabs_preserves_h500_*` |
| P4 | `SessionStateStore` / `SessionSnapshot` | `test_p4_*` |
| P5 | SharedFixed via `SessionOriginPolicy` + `realearth.mp.json` | `test_p5_*` |
| P6 | `DensityBudget` + `clamp_prefabs_in_chunk` inside stamp planner | `test_stamp_prefabs_applies_density_budget_*` |
| P7 | `CdnTilePolicy` + TileStreamer CDN URL | `test_p7_*` |
| P8 | AbsoluteHeightStore (SparseYScaffold section math removed as dead) | `test_p8_*` |

Also: `InjectPatchStats`, `reinject` console, loadgen run manifests.

**Live** inject walk / multi-bot SharedFixed remain **Partial** until dedicated evidence (not offline Done).

---

## Loadgen hooks

| Scenario / tool | Gate |
|---|---|
| `re-selftest-client-path` | Client SM (CI) |
| `re-p0-p1-offline-gate` | expand/fail-closed/plan (CI) |
| `re-phase-offline-gate` | P0-P8 module inventory + pure tests (CI) |
| `re-p1-inject-selftest-manifest` | run.v1 manifest (CI) |
| `re-h500-*` / everest | Live soaks when dedicated up |
| `--stats-json` / `--run-manifest` | Cohort + run metadata for APM |

See sibling `7dtd-loadgen/docs/REALEARTH.md`.

---

## Status discipline

- Offline green = pure APIs + C# build + scenario registry.
- Do not mark live inject/MP **Done** without dedicated evidence.

## Related docs

| Doc | Role |
|---|---|
| [MODIFICATIONS](MODIFICATIONS.md) | Status Done/Partial/Needed |
| [GAP_HARMONY_MODLETS](GAP_HARMONY_MODLETS.md) | How + which 7D API |
| [realearth-runtime](realearth-runtime.md) | Streamed architecture lessons |
| [TODO](../TODO.md) | Executable tickets |
| Loadgen RE scenarios | [`../../7dtd-loadgen/docs/REALEARTH.md`](../../7dtd-loadgen/docs/REALEARTH.md) |

## Changelog

- **2026-07-19:** Ownership header; live inject/MP evidence bar; related docs.
