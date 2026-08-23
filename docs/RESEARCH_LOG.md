# Research log (chronological)

**Owns:** chronological research session log.  
**Not:** canonical status ([MODIFICATIONS](MODIFICATIONS.md)), generic engine hub ([research INDEX](../../7dtd-research/docs/INDEX.md)).  
**Hub:** [INDEX](INDEX.md).


## 2026-07-15 - Initial comprehensive pass

### Done

- Read official blogs/release notes: 2.5, 2.6, 3.0 Dead Hot Summer, 3.0.1 Stable, TFP×Behaviour.
- Read TFP forum V3.0.1 Stable thread (hotfixes, save/server community reports).
- Read wiki.gg XUi docs (3.0 NCalc `{% %}`, folder renames, custom binding registration).
- Reviewed Steam RWG guide (biomes.png exact colors, GeneratedWorlds workflow, rwgmixer).
- Reviewed Nexus custom heightmap importer constraints (16-bit PNG, 255 height, ~8k).
- Reviewed region/save layout (`.7rg`, corruption ops).
- Confirmed Earth data candidates (Copernicus GLO-30, SRTM, Terrarium, WorldPop, OSM, Natural Earth).
- Wrote `docs/RESEARCH_NOTES.md`, `docs/GAME_VERSION.md`.
- Retargeted DESIGN/README/ModInfo from “2.x” to **3.0.1**.

### Key conclusion

Vanilla remains a **finite flat world**. Planetary 1:1 requires streaming + wrap; Phase 0 is heightmap export into existing custom-world tooling.

### Next research sessions

1. Live 3.0.1 install: biome RGB dump, Harmony target map, heightmap importer verify.
2. Diff `rwgmixer.xml` / biomes / XUi_InGame vs 2.5 assumptions.
3. Measure `.rte` decode + sample cost for 7×7 tile hotset.
4. Watch TFP news for post-3.0.1 experimental branches.

## 2026-07-15 - Web map viewer

### Done

- Added static viewer under `viewer/` (flat canvas + Three.js globe).
- `realearth export-viewer` mosaics packs to PNG + `viewer.json`.
- `realearth serve` hosts `viewer/` on port 8765.
- Layers: hybrid, elevation hillshade, landcover, population; settlements; probe lon/lat.

## 2026-07-15 - Modding website references

### Done

- Indexed **7daystodiemods.com** (install guide, Harmony folder policy, Discord, publish path).
- Indexed **7d2dmodding.wiki.gg** (V3.0 XPath/Harmony/sandbox/world categories).
- Linked official wiki Modding Resources, Nexus, TFP XPath thread, Guppy Discord.
- Wrote `docs/MODDING_REFERENCES.md`; linked from research notes + README.

## 2026-07-15 - Single continuous in-game map

### Done

- Documented Baked vs Streamed in `docs/SINGLE_WORLD.md`.
- `realearth bake-world`: one heightmap+biomes world (2048-16384) for one save.
- C#: `WorldSession`, `ChunkTerrainSampler`, `RuntimeHooks` (reflection Harmony).
- Config: `MapMode`, `SingleWorldSession`, spawn lon/lat, `LocalWindowSize`.
- Product intent: fully usable as **one** large map session, not multi-map hopping.

## 2026-07-16 - Map labels, lon/lat limits, API gaps, doc hub

### Done

- City map labels: **discover at city edge**, pin at geographic **center** (trader-like). Edge from map data (`edge_radius_m` / density blob), not fixed band radii.
- Docs: `CITY_MAP_LABELS.md`, `LON_LAT.md` (dual coords, distortion, missing geodesic/antimeridian).
- Docs: `GAP_HARMONY_MODLETS.md` (40-gap matrix, Harmony/XML surfaces, **vs other 7D APIs**: IModApi, XPath, XUi, WebMod, bake, expand).
- Docs hub: `INDEX.md` with ownership table + reading paths.
- DESIGN §18 idea backlog; README/AGENTS reorganized toward INDEX.
- Pipeline: measure urban edge from density; settlements schema carries `edge_radius_m`.

### Key conclusions

1. Map names are session discovery, not atlas dump.
2. Lon/lat is truth; engine XZ is a sliding host; do not confuse them.
3. RealEarth product stack is IModApi + Harmony + binary expand + packs; XML/XUi support only.
4. Next engineering priority remains **live height inject retarget**, not more XML.

### Next research sessions

1. Live 3.0.1 inject soak (H500 → Everest) with expand on client + dedicated.
2. Save/reload absolute session + city discovery persistence design.
3. Pack quality scorecard fields in `earth.manifest.json`.
4. Optional XUi lon/lat HUD prototype (bindings only).

## 2026-07-18 - Runtime lessons into research docs

### Done

- Captured Streamed product runtime architecture lessons from P0-P8 offline cores and multi-campaign adversarial reviews into `7dtd-research/docs/`:
  - `realearth-runtime.md` (dual coords, inject gate, tile readiness, tall crust, slide/claims, verification bar)
  - `realearth-review.md` (failure class catalog, residual risks, module map)
  - `realearth-runtime.md` (stream bubble, origin slide checklist, city edge geometry)
- Linked from `7dtd-research/docs/INDEX.md`, `7dtd-research/docs/terrain-height.md`, and this product `INDEX.md`.

### Key conclusions locked into research

1. Fail-closed missing tiles and expand product guard are non-negotiable on product path.
2. Gen-thread sync tile load + miss-TTL bypass prevent permanent ocean races.
3. Tall columns: dual-fill hardMax solid; above that crust+plug+air (no full Everest Reflect).
4. Stamp surface Y is int32; uint8 wraps bury H500+.
5. Claims PPL is GameManager-scoped; stage-commit remap; uninspectable → freeze SoloSlide.
6. Offline green (build + pure tests + structure) is not live inject/MP Done.
7. Residual: SoloSlide mesh reinject, live Harmony soaks, hollow tall interiors, `.7rg`/light/stability.

### Next research sessions

1. Live inject soak evidence under expand (still product Needed).
2. SoloSlide full chunk voxel reinject design.
3. Keep residual list honest when offline campaigns report zero open critical.

## 2026-07-18 - Doc ownership split (product vs research)

### Done

- Moved RealEarth product narratives into this tree:
  - `docs/realearth-runtime.md`
  - `docs/realearth-surfaces.md`
  - `docs/realearth-review.md`
- `7dtd-research/docs/` keeps **generic** dedicated-engine RE only (loop, entity-ai, terrain-height, save-region, network, …).
- Product INDEX ownership + reading paths updated; research INDEX links product for Streamed deep-dives.

## 2026-07-18 - Engine surfaces IL RE (research)

### Done

- New dump tool: `7dtd-optimizer/tools/DumpRealEarthSurfaces.cs`.
- New dump set: `7dtd-research/il/realearth-surfaces-v3.1.0/` (~405 IL/call files).
- Narratives:
  - `7days-realworld/docs/realearth-surfaces.md` (chunk index, height APIs, region type map, expand state)
  - `7days-realworld/docs/realearth-surfaces.md` (stock Origin fan-out, PPL `m_lpBlockMap`)
- Closed: GetBlock/density Y banding (`y >> 2`, layer height 4); `GetPersistentPlayerList` = GM field; generateTerrain trampoline; Origin DoReposition fan-out; terrain heightmap always `byte[]`.

### Key measurements

| Fact | Value |
|---|---|
| Live dedi `ChunkBlockYDim` | **256** (stock again; expand dump from 07-16 historical) |
| Terrain heightmap | `byte[] m_TerrainHeight[x+z*16]` |
| Auto Origin distance² | 67600 (≈260 m) |
| Chunk save version | 47 (min supported 32) |
| Region chunk ext literal | `.ttc` |
| Claim map | `Dictionary<Vector3i, PersistentPlayerData> m_lpBlockMap` |

### Still open (RE)

- RegionFileRaw sector payload wire format (headers measured; blob codec open).
- Full light/stability site patch regression list after each TFP update.
- Stock Origin vs SoloSlide interaction design.
- WorldState.SaveLoad body.

### Follow-up same day (save/light pass)

- **`Chunk.write`/`read` loop bound = hardcoded 64** (not WorldConstants load). Tall layers need IL rewrite to persist.
- **`World.toBlockY` = `y & 255`**.
- **`Chunk.RefreshSunlight`** walks y from 255 down.
- RegionFileRaw: 8×8 chunks/region, sectorsStartOffset=779.
- `Entity.OriginChanged`: physicsPos/physicsTargetPos + emodel only.
- Product `engine_patcher` already targets 64/256/255 in Y-bound methods; RE list is the audit checklist.

## Related docs

| Doc | Role |
|---|---|
| [RESEARCH_NOTES](RESEARCH_NOTES.md) | Living notes |
| [INDEX](INDEX.md) | Product hub |
| [research INDEX](../../7dtd-research/docs/INDEX.md) | Generic RE |

## Changelog

- **2026-07-19:** Ownership header; related docs.
