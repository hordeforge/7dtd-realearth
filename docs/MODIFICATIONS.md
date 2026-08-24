# Modifications beyond removing height limits

**Owns:** product surface **status** (what exists vs open) by layer A-H.  
**Not:** how to implement each gap or which 7D API ([GAP_HARMONY_MODLETS](GAP_HARMONY_MODLETS.md)); stock engine limit map ([ENGINE_LIMITATIONS](ENGINE_LIMITATIONS.md)). Hub: [INDEX](INDEX.md).

Raising YDim is necessary and not sufficient. Status tags: [INDEX](INDEX.md) (Done / Partial / Needed / Later / Ops).

---

## 0. Orientation

```text
                    ┌─────────────────────────────────────┐
                    │ A. Binary / install modifications   │
                    │    (Assembly-CSharp, both installs) │
                    └─────────────────┬───────────────────┘
                                      │ enables tall columns
                    ┌─────────────────▼───────────────────┐
                    │ B. Harmony / runtime inject         │
                    │    (heights, gen, session, stream)  │
                    └─────────────────┬───────────────────┘
                                      │ feeds from
                    ┌─────────────────▼───────────────────┐
                    │ C. Coordinate + streaming systems   │
                    │ D. Data pipeline + packs            │
                    │ E. Population / settlements         │
                    │ F. Multiplayer / persistence        │
                    │ G. Content / UX / sim budgets       │
                    │ H. Ops / version matrix             │
                    └─────────────────────────────────────┘
```

Y-expand is only **A (vertical)**. Everything below is the rest of the product surface.

---

## A. Binary / install modifications (not only YDim)

| Modification | Purpose | Status |
|---|---|---|
| **YDim + layer count + Y-bound IL** | Tall columns, consistent alloc/free | **Partial** (patcher ships; live soak still open) |
| **Do not rewrite XZ map size 256** | Avoid corrupting 16×16 height/biome maps | **Done** (patcher design) |
| **Expand client + dedicated** | Same ceiling both ends | **Needed** (ops discipline every update) |
| **Backup / restore / re-apply after Verify** | Steam undoes expand | **Done** scripts; **Needed** operator habit |
| **Optional: sparse column storage** | RAM at planet scale with tall Y | **Later** ([`DYNAMIC_CHUNK_HEIGHT.md`](DYNAMIC_CHUNK_HEIGHT.md)) |
| **Optional: save-format awareness** | `.7rg` / region packing with tall Y | **Needed** (validate; may need more IL or sidecar) |

Height limits are **one slice of A**. Save/region and sparse Y are still binary-adjacent hard problems.

---

## B. Harmony / managed runtime modifications

Stock terrain and world gen do not know about Earth DEM. Expand alone still yields empty or RWG land unless inject wins.

| Modification | Targets / surface | Status |
|---|---|---|
| **Height query override** | All concrete height APIs (see research `terrain-height.md`); never interface-only; **byte returns stay lossy** | **Partial** (`RuntimeHooks` + `HeightQueryPatcher` + `InjectPatchStats`) |
| **Terrain generate rewrite** | `GenerateTerrain` / provider fill → solid+density from RealEarth | **Partial** (`GenerateTerrainPostfix` → `ChunkTerrainInject`) |
| **Fail-closed missing tiles** | No fake DEM peaks when `.rte` missing | **Partial** (`TileSamplePolicy` on sampler + EngineHeight product path; live proof open) |
| **Expand product guard** | Refuse real-height claims on stock YDim | **Partial** (`ExpandProductGuard`; live expand soak open) |
| **Session origin policy** | SoloSlide / SharedFixed / fold | **Partial** (`SessionOriginPolicy` wired into WorldSession) |
| **Surface-Y stamps** | Prefab Y on real DEM surface | **Partial** (`StampSurfaceY` + density.stamp_prefab_root_y) |
| **Session snapshot** | Absolute origin save/reload JSON | **Partial** (`SessionStateStore`; hooked to stock `SaveWorld` / `SaveWorldState`, live proof open) |
| **Density budgets** | Cap stamps / sleeper weights | **Partial** (`DensityBudget`) |
| **CDN tile URL + fail-closed** | Optional CDN; miss → sample policy | **Partial** (`CdnTilePolicy`) |
| **Sparse Y scaffold** | Section index math for tall columns | **Removed** (dead scaffold; AbsoluteHeightStore keeps the sparse surface cache) |
| **Chunk load / index hooks** | Stream tiles when chunks enter range | **Partial** (`ChunkIndexPostfix`, streamer) |
| **World ready / player tick** | Center origin, refresh stream bubble, session | **Partial** (`WorldReadyPostfix`, `PlayerTickPostfix`) |
| **RWG generator types** | `TerrainGeneratorWithBiomeResource` etc. still sample stock | **Needed** (retarget if missed on live DLL) |
| **Decoration / biome paint from landcover** | After height, paint biomes / density underlay | **Partial / Needed** |
| **Prefab / sleeper Y after surface known** | Avoid float/bury on real DEM | **Needed** |
| **Water fill from DEM / masks** | Coasts, lakes (not deep trench product) | **Later** |
| **Stability / light / mesh fallout** | After tall inject, fix breakage | **Needed** (validate under expand) |
| **Console diagnostics** | `reheight` for sea+elev proof | **Done** |
| **Fail soft per hook** | Missing target → log, do not kill mod | **Done** pattern; keep it |

**Rule:** Y-expand without complete height+gen inject = tall empty columns or stock noise. Inject without expand = clamp/clip (product rejects compress).

---

## C. Coordinate and streaming systems (new code, not TFP features)

| Modification | Purpose | Status |
|---|---|---|
| **Absolute Earth grid** | lon/lat ↔ block X/Z (equirectangular) | **Done** (`EarthCoords`; limits in `LON_LAT.md`) |
| **Regional bbox mapping** | Demo packs in finite width | **Done** (manifest override; linear stretch) |
| **WorldSession origin** | Local host ↔ absolute Earth | **Done** scaffold |
| **LocalWindowSize host canvas** | Keep engine coords bounded (~1024) | **Done** config; **Needed** live SoloSlide proof |
| **Longitude wrap** | Circle planet on X | **Partial** (config; full-planet packs; soak open) |
| **Lat-correct horizontal meters / geodesic** | True km at high lat | **Missing** |
| **Antimeridian-safe bboxes** | Pacific / dateline packs | **Missing** |
| **TileStreamer bubble** | Load/unload `.rte` by radius | **Partial** |
| **CDN / missing tile policy** | Fetch or fail closed | **Partial** (`CdnTilePolicy` + streamer fetch; farm/CDN ops open) |
| **Baked vs Streamed modes** | Finite GeneratedWorld vs inject | **Partial** (Baked path stronger today) |
| **SingleWorldSession policy** | One continuous save, no map hop | **Done** intent / config |

These are **first-class product systems**. They are not free with YDim.

---

## D. Offline data pipeline modifications

Engine never sees Copernicus/GHSL unless you build packs.

| Modification | Purpose | Status |
|---|---|---|
| **`.rte` tile format + manifest** | Streamable DEM/landcover/pop | **Done** |
| **DEM ingest** (Terrarium, GeoTIFF, …) | Real elevation meters | **Done** / source-dependent |
| **Landcover → biome** | Recognizable biomes | **Partial** |
| **Bake-world export** | Finite playable GeneratedWorld | **Done** path |
| **Height-test / H500 / Everest packs** | Validate expand + 1:1 | **Done** tools |
| **Reproducible pack manifests** (URLs, hashes, license) | Auditable 1:1 claim | **Needed** |
| **Planet tile farm + indices** | Full Earth coverage | **Partial** (`planet-tiles`); farm ops **Needed** |
| **Seam / no-data / mixed resolution** | Tile edges, DEM holes | **Needed** |
| **Legal pipeline** (no Google bulk) | Attribution, allowed sources | **Done** policy |

---

## E. Population density and settlements

Geography without people is empty wilderness. Separate from height.

| Modification | Purpose | Status |
|---|---|---|
| **Population channel in tiles** | Log-scaled density field | **Partial** |
| **GHSL / WorldPop / built-up ingest** | Real human geography | **Partial** (optional geotiff hooks) |
| **Density → stamp bands** (metro…hamlet) | City intensity without OSM meshes | **Partial** |
| **Named places / settlements.json** | Discovery labels, seed peaks | **Partial** (data + seeds) |
| **City map labels (discover-on-approach)** | Edge unlock from map data, pin at center | **Done** (session; `edge_radius_m`; see `CITY_MAP_LABELS.md`) |
| **Prefab placement on real surface Y** | After inject | **Needed** |
| **Road snap (OSM)** | Highways as corridors | **Later** |
| **Sim pressure weights** (zombies/sleepers by density) | Metro harder than plains | **Later** (cap or melt) |
| **Density caps / LODs** | Engine cannot sim true Tokyo entity count | **Needed** for scale |

---

## F. Multiplayer and persistence

| Modification | Purpose | Status |
|---|---|---|
| **Shared origin policy** (`SharedFixed` / no per-client window) | Combat/claims work | **Partial** config; **Needed** live MP proof |
| **Per-player tile bubbles, one world** | Data stream ≠ private coords | **Partial** design |
| **Identical expand on all peers** | Tall Y desync | **Ops / Needed** |
| **Player build deltas per tile** | Survive unload + pack update | **Needed** |
| **Server authoritative stream** | Dedicated hosts or proxies tiles | **Needed** for true online |
| **Save/reload absolute session** | Spawn, origin, stream state | **Partial** (`SessionStateStore` + save hooks; live proof open) |

---

## G. Content, UX, and simulation budgets

| Modification | Purpose | Status |
|---|---|---|
| **XML modlet** (biomes, spawns, rwg helpers) | Support role | **Partial** |
| **Globe / world map UI** | Planet context | **Viewer only** (offline web viewer; in-game scaffold removed) |
| **Map FOW / discovery** | Explore real places | **Partial** (FOW debug + city edge discovery) |
| **Climate / weather refinement** | Beyond landcover | **Later** |
| **Rivers / hydrology overlays** | Recognizable waterways | **Later** |
| **View distance / stream radius tuning** | FPS under dense DEM+city | **Needed** (measure) |
| **Entity/POI budgets in dense cells** | Protect main thread | **Needed** at city scale |
| **Accept prefab kits ≠ real buildings** | Product honesty | **Done** (policy) |

---

## H. Ops, packaging, version matrix

| Modification | Purpose | Status |
|---|---|---|
| **net48 mod build against live Managed** | API match | **Done** scripts; **Needed** after each update |
| **Proton GeneratedWorlds path** | Client New Game list | **Done** install path |
| **Package `Tools/` expand with mod** | Ship expand with product | **Done** packaging intent |
| **Compatibility matrix** (DLL hash, YDim, Harmony) | Refuse silent wrong build | **Needed** |
| **EAC off documentation** | Modded servers | **Done** notes |
| **Retarget checklist** after TFP patch | Hooks + expand sites | **Needed** (formalize) |

---

## Priority (P0-P8)

```text
P0  Y-expand correct (A) · re-validate every update
P1  Height + GenerateTerrain inject live 3.1.0 (B)
P2  Streamed session, tile bubble, fail-closed tiles (C)
P3  Density stamps + biome underlay on real surface (E + B)
P4  Save/reload + build deltas (F)
P5  SharedFixed co-located MP proof (F)
P6  Density/sim budgets + net soak (G)
P7  Planet farm + CDN (D)
P8  Sparse Y / roads / climate (Later)
```

Implementation how-to and API choice: [GAP_HARMONY_MODLETS](GAP_HARMONY_MODLETS.md). Tickets: [TODO](../TODO.md).

## Anti-scope

AI/mesh optim → `7dtd-server-optimizer`. Load bots → `7dtd-loadgen`. Google 3D cities → forbidden ([REALISM](REALISM_AND_GOOGLE_EARTH.md)). Cadastral rebuild → non-goal ([DESIGN](../DESIGN.md)).

---

## Related docs (do not re-author status there)

| Doc | Role |
|---|---|
| [GAP_HARMONY_MODLETS](GAP_HARMONY_MODLETS.md) | How to close gaps + which 7D API |
| [ENGINE_LIMITATIONS](ENGINE_LIMITATIONS.md) | Stock blockers this status responds to |
| [HEIGHT_LIMITS](HEIGHT_LIMITS.md) | Vertical product policy |
| [LON_LAT](LON_LAT.md) | Coord math (section C detail) |
| [ABSOLUTE_STREAMING](ABSOLUTE_STREAMING.md) | Absolute → inject path |
| [realearth-runtime](realearth-runtime.md) | Streamed architecture lessons |
| [realearth-surfaces](realearth-surfaces.md) | Engine surfaces used by product |
| [realearth-review](realearth-review.md) | Adversarial failure catalog |
| [IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md) | P0-P8 order |
| [TODO](../TODO.md) | Executable tickets |
| Generic engine RE | [`../../7dtd-engine-research/docs/INDEX.md`](../../7dtd-engine-research/docs/INDEX.md) |

## Changelog

- **2026-07-18:** Related docs hub links; status remains sole home for Done/Partial/Needed.
