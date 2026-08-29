# RealEarth design

**Target game:** 7 Days to Die **V3.2.0** (Henpocalypse)  
**Product name:** RealEarth  
**This document:** architecture and product intent. Operator install: [`README.md`](README.md), [`docs/MODLET.md`](docs/MODLET.md).

---

## 1. Goal

Build a **1:1 replica of real Earth geography and population density** inside 7 Days to Die:

| Dimension | 1:1 meaning |
|---|---|
| **Horizontal** | 1 block = 1 meter on the ground (equatorial scale) |
| **Vertical** | 1 block = 1 meter of real elevation (no product-path height compression) |
| **Coastline / terrain shape** | Real DEM + landcover, not RWG noise |
| **Where people live** | Real population-density fields drive settlement intensity |
| **Travel** | Continuous world: walk or drive from one real region toward another without map hops |

The player should recognize **where they are** from the land shape, coast, mountain scale, and how built-up the area feels, then play 7DTD survival/combat on that stage.

### 1.1 Success criteria (product)

A release is successful when all of the following hold for a chosen region (and, over time, for arbitrary Earth tiles):

1. **Geography:** elevation and coastlines match open DEM within the tile resolution; peaks use **real meters**, not a 0–255 global squash.
2. **Land surface:** landcover paints plausible biomes (forest, desert, snow, water, urban underlay).
3. **Population density:** high-density grids produce dense settlement stamping and harder urban pressure; empty wilderness stays sparse.
4. **One session:** one save / one coordinate story (`SingleWorldSession`), not a menu of disconnected maps.
5. **Reproducible data:** every pack carries a manifest (bounds, sources, versions, license pointers).

### 1.2 Explicit non-goals

| Not a goal | Why |
|---|---|
| Photoreal buildings / Google 3D cities | Wrong data rights; not voxel-native |
| Every real structure as a unique prefab | Impossible at planet scale; use density bands + stamps |
| Full planet resident in RAM | Engine and disk cannot hold ~40,075 km at once |
| Replacing 7DTD combat / netcode | Vanilla shared coords and chunks already work |
| Height compression as the ship mode | Product is real height; expand is required |

---

## 2. Why the engine forces this architecture

At 1 block = 1 m:

| Quantity | Approx. value |
|---|---:|
| Earth circumference (equator) | 40,075,017 m → **~40M blocks** wide |
| Pole-to-pole (equirectangular) | ~20,003,931 blocks |
| Everest | ~8,849 m → **~8,849 blocks** above sea (plus seaLevelY) |
| Mariana Trench | ~11,000 m below sea |
| Stock 7DTD column height | ~**0–255** blocks without expand |
| Practical loaded world edge | ~**16,384** blocks (~16 km) |

Implications:

1. **Never** build one global heightmap (~8×10¹⁴ surface cells). Always **tiles**.
2. **Never** hold the whole planet in Unity. Always **stream** data into vanilla chunks.
3. **Stock YDim cannot hold real mountains.** Product vertical needs RealEarth **YDim expand** + 1:1 inject. See [`docs/HEIGHT_LIMITS.md`](docs/HEIGHT_LIMITS.md).
4. Multiplayer must keep **one shared absolute coordinate story** so shooting and claims work. See [`docs/MULTIPLAYER_STREAMING.md`](docs/MULTIPLAYER_STREAMING.md).
5. Lon/lat is equirectangular dual coords (truth vs host XZ). Distortion, wrap/poles, regional bbox, and gaps: [`docs/LON_LAT.md`](docs/LON_LAT.md).

---

## 3. Product principles

1. **Real data over procedural fantasy.** Prefer open DEM, landcover, population; RWG is not the geography source.
2. **Real meters over feel-curves.** `gameY = seaLevelGameY + elev_m` (1 m = 1 block). No global compress on the product path.
3. **Density over cadastral truth.** Population grids and built-up rasters drive how “city-like” a place is; prefabs are 7DTD stamps, not OSM building meshes.
4. **Stream by need.** Absolute Earth is virtual; only nearby `.rte` tiles and vanilla view/sim chunks are hot.
5. **One world session.** Baked region or Streamed Earth, still one continuous play space.
6. **Expand is part of the product.** YDim expand lives in this mod (`Tools/`, `make engine-expand`), not in EfficientServer/APM.
7. **Legal sources only.** No Google Earth / Maps bulk scrape. See [`docs/REALISM_AND_GOOGLE_EARTH.md`](docs/REALISM_AND_GOOGLE_EARTH.md) and [`ATTRIBUTION.md`](ATTRIBUTION.md).

---

## 4. System architecture

```text
                    Open Earth data (offline)
         DEM · landcover · population · places · water · roads
                              │
                              ▼
                 ┌────────────────────────────┐
                 │  Python pipeline (tools/)  │
                 │  build-region / tile farm  │
                 │  → .rte tiles + manifest   │
                 │  → optional bake-world     │
                 └─────────────┬──────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                                 ▼
     Baked GeneratedWorld              Streamed tile pack
     (finite region, 2k–16k)           (absolute Earth tiles)
              │                                 │
              └────────────────┬────────────────┘
                               ▼
                 ┌────────────────────────────┐
                 │  RealEarth.dll (net48)     │
                 │  WorldSession + streamer   │
                 │  Harmony height/biome inject│
                 │  density → urban / POIs    │
                 └─────────────┬──────────────┘
                               ▼
                 Vanilla chunk engine + shared coords
                 (load/unload, combat, multiplayer)
```

| Layer | Owns | Does not own |
|---|---|---|
| Offline `tools/realearth` | Pack build, bake, viewer export, engine audit helpers | Live game loop |
| Runtime `Source/RealEarth` | Coords, stream, inject, config, height policy | Fake clients (see `7dtd-loadgen`) |
| YDim expand (`Tools/`) | Raise column ceiling in `Assembly-CSharp` | Optimizer / APM |
| Vanilla engine | Chunks, net, combat, save format | Planetary DEM |

---

## 5. Coordinate model

### 5.1 Absolute Earth grid

Equirectangular block mapping (streamable, longitude-wrap friendly):

```text
lon = (X / WORLD_WIDTH)  * 360 - 180     # X in [0, WORLD_WIDTH)
lat = 90 - (Z / WORLD_HEIGHT) * 180      # Z in [0, WORLD_HEIGHT)
```

At 1:1:

- `WORLD_WIDTH`  ≈ 40,075,017  
- `WORLD_HEIGHT` ≈ 20,003,931  

Regional packs may use a **bbox** mapped linearly into a smaller `WorldWidth × WorldHeight` (still 1 m/block inside the pack).

| Axis | Behavior |
|---|---|
| **X (longitude)** | Wraps: circling the planet is a product goal |
| **Z (latitude)** | Clamps at poles; polar meters-per-degree distortion accepted for v1 |

### 5.2 Engine local space

The engine only ever holds a **finite host**. Defaults:

| Knob | Default | Role |
|---|---:|---|
| `LocalWindowSize` | 1024 | Sliding/fixed host canvas (not “always fully meshed”) |
| `TileSize` | 512 | Earth data tile edge (meters/blocks) |
| `StreamRadiusTiles` | 2–3 | Hot `.rte` bubble around players |
| `UnloadRadiusTiles` | 4+ | Drop cold tiles |

**Absolute Earth** is ground truth. **Local origin** may slide (`SoloSlide`) or stay fixed (`SharedFixed` for co-located MP). Details: [`docs/ABSOLUTE_STREAMING.md`](docs/ABSOLUTE_STREAMING.md), [`docs/SINGLE_WORLD.md`](docs/SINGLE_WORLD.md).

### 5.3 Two play modes

| Mode | What it is | Best for |
|---|---|---|
| **Baked** | One GeneratedWorld heightmap+biomes+density stamps (2k–16k) | Simple MP, region demos |
| **Streamed** | Same vanilla chunks; height/biome/density from absolute `.rte` | Long travel, multi-region, full Earth path |

Both are **one continuous session**. Streamed is the long-term planetary mode; Baked is the reliable finite slice.

---

## 6. Geography stack (1:1 land)

### 6.1 Elevation (required)

| Source class | Role |
|---|---|
| Copernicus GLO-30 / SRTM / Terrarium / GeoTIFF | Surface elevation meters |
| Optional bathymetry later | Ocean floor columns |

**Inject policy (product):**

```text
gameY = seaLevelGameY + elev_m     # 1 m = 1 block
```

capped by `EngineMaxGameY` (default 29000 = sea 16000 + airliner 12000 + headroom) and the expanded column max (YDim 32768).

| Component | Role |
|---|---|
| `.rte` elevation channel | Real meters (zlib) |
| YDim expand | Required so columns can exceed stock ~255 |
| Harmony inject | Sample + fill chunk solid/air for true gameY |
| `EngineHeightStockSafe` | **Opt-in only** compress on stock engines; **not product** |

Docs: [`docs/HEIGHT_LIMITS.md`](docs/HEIGHT_LIMITS.md), [`docs/DYNAMIC_CHUNK_HEIGHT.md`](docs/DYNAMIC_CHUNK_HEIGHT.md).

### 6.2 Landcover and climate

| Source class | In-game use |
|---|---|
| ESA WorldCover / similar | Biome paint |
| Climate (optional later) | Snow line, arid vs temperate refinement |
| Water masks / HydroSHEDS / OSM water | Coasts, lakes, rivers |

Sketch mapping (tunable):

| Landcover | 7DTD direction |
|---|---|
| Forest | forest / pine_forest |
| Grass / crop | open / burnt-adjacent variants |
| Bare / sand | desert |
| Snow / ice | snow |
| Water | water |
| Urban | urban/wasteland underlay + density stamps |

### 6.3 Hydrology and roads (phased)

| Feature | Data | In-game |
|---|---|---|
| Rivers / lakes | Hydro + OSM | Water columns, banks |
| Roads | OSM | Surface strips, spawn corridors, stamp anchors |

Not required for first 1:1 height demos; required for “recognizable cities and highways.”

---

## 7. Population density stack (1:1 human geography)

Geography without people is empty wilderness. The second half of the product is **where humans actually concentrate**.

### 7.1 Signals

| Signal | Role |
|---|---|
| **Population density grid** (GHSL / WorldPop) | Primary urban intensity (people/km² → tile channel) |
| **Built-up surface** (GHS-BUILT, optional) | Fabric where pop grids are coarse |
| **Named places** (Natural Earth / GeoNames) | City names, seed peaks, discovery labels |

Stored per tile as a **population channel** (log-scaled 0–255 for pack compactness) plus optional settlement side-car JSON.

### 7.2 Density → game systems

```text
population field
    │
    ├─► urban biome underlay (high density)
    ├─► prefab stamp intensity + pack band (metro → hamlet)
    ├─► trader / POI chance
    ├─► zombie / sleeper pressure weight (design target)
    └─► globe / map discovery markers (edge unlock → pin at center)
```

In-game map labels: [`docs/CITY_MAP_LABELS.md`](docs/CITY_MAP_LABELS.md). Density stamps: [`docs/CITIES_AND_DENSITY.md`](docs/CITIES_AND_DENSITY.md).

Bands (see [`docs/CITIES_AND_DENSITY.md`](docs/CITIES_AND_DENSITY.md)):

| Band | Density (qualitative) | Stamp intent |
|---|---|---|
| metro | very high | downtown / commercial packs |
| large_city | high | dense mixed urban |
| town | medium | strip + mixed housing |
| village | low–medium | rural cluster |
| hamlet | low | sparse cabins/farms |
| rural_scatter | sparse | isolated POIs |

### 7.3 Honest fidelity bar

| We do | We do not |
|---|---|
| Match **where** density peaks (Tokyo ≠ Kansas) | Reconstruct every real building footprint |
| Scale stamp count and pack style by density | Import Google 3D or OSM mesh cities as-is |
| Keep wilderness sparse | Fill empty DEM with fake RWG megacities |

Prefabs remain **vanilla/compatible POI kits** placed from density and road anchors. That is the correct 7DTD representation of population, not a city builder.

---

## 8. Tile pack format

Each `.rte` tile covers `TileSize × TileSize` blocks (default **512 m**).

```text
magic: "RTE1"
tile_x, tile_z: int32
version, flags: uint16
width, height, reserved: uint32
elevation: zlib uint16[N]     # real meters; fixed +11000 m offset, scale 1 (tile_format.py / RteTile.cs)
landcover: zlib uint8[N]
population: zlib uint8[N]     # log-scaled density
optional: poi blob             # water/road masks are future work (see §6.3)
```

Each channel is a u32 length prefix followed by its zlib blob. Decoders
(`tile_format.py` / `RteTile.cs`) reject `version > 1` so a future layout change
fails closed instead of misdecoding as v1 terrain.

On disk:

```text
pack/
  earth.manifest.json      # CRS, tile size, bbox or planet, sources, name/version
  tiles/{tz}/{tx}.rte
  settlements.json         # optional named cores
  export_7dtd/             # optional bake images
```

Content-addressed by tile index. Runtime loads a **bubble** around players; optional HTTP CDN base for missing tiles (`TileCdnBaseUrl`).

**Player edits** should eventually persist as **per-tile deltas** so base Earth packs can update without wiping bases (design target; see TODO).

---

## 9. Runtime (C# mod)

| Piece | Responsibility |
|---|---|
| `ModApi` | Load config, init height module, streamer, session |
| `WorldSession` | Local ↔ absolute Earth mapping, origin policy |
| `TileStreamer` | Ensure/unload `.rte` around absolute position |
| `ChunkTerrainSampler` / `ChunkTerrainInject` | Real-height sample + column fill |
| `EngineHeight*` | Expand detection, 1:1 policy, meter store |
| Harmony height queries | All relevant `GetTerrainHeight*` / generate paths |
| Config JSON | Mode, paths, stream radii, height policy, spawn lon/lat |

Config product defaults (see `Config/realearth.json`):

```json
{
  "MapMode": "Streamed",
  "SingleWorldSession": true,
  "SeaLevelGameY": 16000,
  "EnableEngineHeightMod": true,
  "EngineHeightOneToOne": true,
  "EngineHeightStockSafe": false,
  "EngineMaxGameY": 29000,
  "LocalWindowSize": 1024,
  "TileSize": 512,
  "StreamRadiusTiles": 2,
  "EnableLongitudeWrap": false
}
```

Shipped regional packs keep `EnableLongitudeWrap=false` until a full-planet pack is installed. Code and config share stream radii **2/4** with the default JSON.

Install path for product height: **`make install-full`** (expand + mod), not “mod only + compress.”

---

## 10. Offline pipeline

Python package under `tools/` (`uv` only):

| Command family | Purpose |
|---|---|
| `build-region` | Bbox → DEM + landcover + population → `.rte` pack |
| `demo` | Synthetic offline pack for CI / no network |
| `bake-world` | Finite GeneratedWorld export (height/biomes/density stamps) |
| `height-test-map` | Everest / H500 validation packs |
| `export-viewer` / `serve` | Web flat + globe inspection |
| `sample-chunk` | Offline proof of absolute sample |
| `planet-tiles` | Index math for full-Earth farms |

Pipeline must record **source URLs/versions/hashes** in the manifest so a “1:1 replica” claim is auditable.

---

## 11. Multiplayer model

Vanilla already provides:

- One shared world space  
- Chunk load/unload  
- Cross-chunk combat  

RealEarth only supplies **terrain/density data** for chunks. Rules:

| Rule | Detail |
|---|---|
| Shared coords | Never per-player private origins for combat |
| Tile bubbles | May differ per player (data only) |
| `SharedFixed` | Preferred when group co-located on a Streamed host |
| `SoloSlide` | Fine for single-player travel |
| Baked | Simplest MP: one finite map, stock netcode |

Full write-up: [`docs/MULTIPLAYER_STREAMING.md`](docs/MULTIPLAYER_STREAMING.md).

---

## 12. Map UX

| Layer | Role |
|---|---|
| Local radar | Neighborhood (stock minimap role) |
| Globe / world map | Planet context, player marker, discovered cities |
| Discovery | Unlock place names when the player reaches a city **edge**; pin at geographic **center** (trader-like sticky markers) |

**In-game implementation:** NavObject class `realearth_city`, catalog from pack `settlements.json` / seeds, **edge from map data** (`edge_radius_m` via density blob or urban bbox), config `ShowCityNamesOnMap` + `CityMapDiscoverRadiusScale`. Full doc: [`docs/CITY_MAP_LABELS.md`](docs/CITY_MAP_LABELS.md).

Viewer (browser) is for **data QA** before/without the game (`viewer/`); it can show all settlements, unlike the in-game discover-on-approach map.

---

## 13. Phased delivery toward full 1:1

| Phase | Outcome | Geography | Population |
|---|---|---|---|
| **P0** | Design + formats + tools + sample region | DEM pack / bake | Seed settlements plan |
| **P1** | Playable Baked region at 1:1 m/block | Real DEM bbox | Density channel + stamps |
| **P2** | Real height product | YDim expand + 1:1 inject validated | Unchanged |
| **P3** | Streamed travel | Absolute tiles + origin policy live-tested | Density inject on stream |
| **P4** | Multi-region / planet farm | Tile CDN or bulk packs | GHSL/WorldPop at scale |
| **P5** | Roads/rivers first-class | OSM/hydro overlays | Stamps snap to network |
| **P6** | MP hardening | SharedFixed / server absolute policy | Same density rules server-side |

Status of “done” pieces lives in [`README.md`](README.md) and [`TODO.md`](TODO.md). Design here is the **target**; do not treat unchecked TODO items as shipped.

These design phases are **not** the `P0-P8` implementation priorities; that vocabulary is owned by [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

---

## 14. Scale modes (config, not competing products)

| Mode | m/block | When to use |
|---|---:|---|
| **1:1** (default product) | 1 | True replica goal |
| region bbox @ 1:1 | 1 | Practical demos (Denver, Everest, …) |
| 1:10 / 1:100 | 10 / 100 | Optional “whole continent on one host” experiments only |

Shrinking scale is a **debug/alt** switch, not the north star. The north star is **1:1 geography + density**.

---

## 15. Data licensing

| Class | Examples | Notes |
|---|---|---|
| Elevation | Copernicus, SRTM, Terrarium | Follow provider terms; attribution |
| Landcover | ESA WorldCover | Often CC BY |
| Population | GHSL, WorldPop | Check product license |
| Places | Natural Earth, GeoNames | Public / mixed |
| Roads/water | OSM | ODbL share-alike on derived DBs |

Every distributable pack ships attribution. **Do not** redistribute restricted products; point builders at user-held downloads when required.

---

## 16. Honest limits (still 1:1 intent)

| Limit | Mitigation |
|---|---|
| Engine ~16 km practical host edge | Stream absolute Earth; small `LocalWindowSize` |
| Stock YDim ~255 | Product expand + real inject |
| Planet data size (TB-class at full 1 m) | Regional packs + CDN; progressive resolution |
| Prefab ≠ real architecture | Density bands + kits; optional future OSM footprint experiments |
| Harmony fragility | Retarget per game build; discovery where TFP renames |
| Polar distortion (equirectangular) | Documented in [`docs/LON_LAT.md`](docs/LON_LAT.md); optional later projection for polar play |

These are engineering constraints, not a retreat from the 1:1 goal.

---

## 17. Repository map

```text
ModInfo.xml
Config/                 # realearth.json, biomes, rwg helpers
Source/RealEarth/       # runtime mod (net48)
tools/realearth/        # offline pipeline (uv)
viewer/                 # web QA map
data/samples/           # demo / height-test packs
worlds/                 # baked outputs
docs/                   # deep dives (height, MP, density, sources)
DESIGN.md               # this file
README.md               # operator entry
TODO.md                 # execution backlog
ATTRIBUTION.md          # licenses
```

### Related docs

**Hub only:** [`docs/INDEX.md`](docs/INDEX.md) (ownership table + reading paths). Do not duplicate that list here.

---

## 18. Idea backlog (design-level, not TODO tickets)

**Only home for product ideas** (other docs link here; do not copy tables).  
Promising directions after P0–P3 are green. None replace inject/expand.

### 18.1 Geography fidelity

| Idea | Value | Cost / risk |
|---|---|---|
| **Progressive resolution tiles** | 1 m near travel corridor, 10–30 m elsewhere | Tile schema + streamer LOD; seaming |
| **Coastline sharpening** | Better harbors/islands at coarse DEM | Hydro mask + manual edit tools |
| **Bathymetry optional** | Continental shelf feel | SeaLevel policy already shallow; deep ocean not a goal |
| **Seasonal snow line by lat/elev** | Recognizable Alps/Himalaya climate | Weather + landcover; soft |

### 18.2 Population and places

| Idea | Value | Cost / risk |
|---|---|---|
| **Trader / mission hubs at real cores** | Quest-friendly without full RWG cities | Prefab Y snap; content balance |
| **Density → gamestage weights** | Metro risk without entity meltdown | Caps required; measure with APM |
| **Persist discoveries by lon/lat** | Atlas grows across sessions | Save format + MP sync |
| **Road-aligned stamp corridors** | Highways feel real | OSM extract + conflict rules |
| **Urban edge polygons** | Better discover radii than density blobs | Schema ready (`edge_radius_m`); bulk data |

### 18.3 UX

| Idea | Value | Cost / risk |
|---|---|---|
| **XUi globe + lon/lat HUD** | “Where am I on Earth?” | V3 XUi churn |
| **Production FOW** (visited Earth tiles) | Explore real places | MapChunkDatabase + absolute keys |
| **Compass-to-city after discovery** | Navigation without spoilers | NavObject settings |
| **Pack passport in F1** | Debug source resolution / expand state | Console only is enough first |

### 18.4 Multiplayer and ops

| Idea | Value | Cost / risk |
|---|---|---|
| **Dedicated absolute authority** | Multi-group planet | Hard; SharedFixed first |
| **Tile CDN with signed manifests** | Large farms | Ops + fail-closed |
| **Loadgen release gate** | Streamed soak before ship | Sibling `7dtd-loadgen` |
| **WebMod expand/pack panel** | Admin sees YDim + pack | Optional; not core inject |

### 18.5 Engine long shots

| Idea | Value | Cost / risk |
|---|---|---|
| **Sparse Y sections** | Tall planet RAM | Deep binary; see DYNAMIC_CHUNK_HEIGHT |
| **Lat-correct horizontal meters** | Honest km at 60°N | Session math + stamp spacing |
| **Antimeridian-safe packs** | Pacific play | Bbox tooling |

Execution tracking: [`TODO.md`](TODO.md). API choice for each idea: [`docs/GAP_HARMONY_MODLETS.md`](docs/GAP_HARMONY_MODLETS.md).

---

## 19. One-sentence summary

**RealEarth is a 1:1 meter-scale Earth stage for 7DTD: real elevation and land shape, real population-density-driven settlement intensity, streamed so the planet fits the engine, with YDim expand so height stays true.**
