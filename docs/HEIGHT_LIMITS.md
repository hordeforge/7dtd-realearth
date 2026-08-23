# Height limits: real height product, stock 255 constraint

**Owns:** product vertical policy (1 m = 1 block, expand required, compress opt-in only).  
**Not:** product surface status ([MODIFICATIONS](MODIFICATIONS.md)), Streamed inject lessons ([realearth-runtime](realearth-runtime.md)), generic stock height IL ([research terrain-height](../../7dtd-research/docs/terrain-height.md)).  
**Stock limit map:** [ENGINE_LIMITATIONS](ENGINE_LIMITATIONS.md). **Install:** [MODLET](MODLET.md). **Hub:** [INDEX](INDEX.md).

## Product policy

**RealEarth does not use global height compression as the product path.**

| Rule | Value |
|---|---|
| Mapping | `gameY = seaLevelGameY + elev_m` (1 m real ≈ 1 block) |
| Data | `.rte` stores real elevation meters |
| Engine | YDim expand required (`make engine-expand` / `make install-full`) |
| Compress | Opt-in only via `EngineHeightStockSafe=true` (experiments, not ship) |

## The hard facts (stock engine without expand)

| Layer | Limit | Notes |
|---|---|---|
| Stock playable / build Y | **~0-255 blocks** | Shipping assemblies (`Height255`, voxel columns) |
| 1 block | **1 m** | Vanilla horizontal and product vertical |
| Real Everest | ~8849 m | Needs expand + 1:1 inject, not a compress curve |
| Mariana Trench | ~−11000 m | Same |
| Stock `dtm.raw` | uint16 = `gameY * 256` | Stock bake band only; not the Streamed product height path |

So: on **stock** YDim=256, true Everest columns are impossible. The product fix is **engine expand**, not remapping Earth into 255.

## Offline helpers (not product inject)

`tools/realearth/height.py` still has `compress_elevation` profiles for tests, stock DTM exports, and the opt-in StockSafe path:

| Profile | Use |
|---|---|
| `one_to_one` | **Product mapping** (sea + elev_m); set max_y high enough |
| `relative` / `local_stretch` | Legacy / opt-in stock experiments only |

Do not bake product worlds assuming compress-into-255 is desired.

## Do we need to mod the game for more height?

**Yes.** Real height worldwide needs taller columns than stock 256.

That is a **deep** engine change (this mod's YDim expand), not a config tweak. Surface area includes (non-exhaustive; names vary by version):

| Area | Why |
|---|---|
| Chunk voxel storage | Columns sized for Y ∈ [0, 255] (byte density / block arrays) |
| Height map / DTM consumers | Assume 8-bit or 0-255 game height after process |
| Mesh / meshing | Vertical loops, face culling, LOD |
| Physics / gravity / fall damage | Fall distance, kill planes |
| Building / stability | Support chains over taller columns |
| POIs / prefabs | Authoring assumes ~255 max roof |
| Networking / saves | Region (`.7rg`) layout may pack Y sparsely or assume height |
| Lighting / occlusion | Vertical range |
| Water / groundwater | Sea level + column fill |
| AI pathfinding | Nav height |

Harmony can **patch** many call sites if you find them, but raising height from 256 → e.g. 1024 or 4096 often means:

- **More RAM per chunk** (linear in height)
- **Breakage** on every TFP update
- **Incompatible saves** with vanilla

There is no mature “just set MaxHeight=4096” mod that is known-good for full 1 m Everest on current 7DTD without serious engineering.

## Recommended RealEarth strategy

### Tier 0: product path (required)

**Real height + YDim expand.** No global compress.

```bash
make install-full   # expand + install (product)
# or:
make engine-expand  # client + dedicated Assembly-CSharp (YDim=16384)
make install
```

Config defaults: `EngineHeightOneToOne=true`, `EngineHeightStockSafe=false`, `EngineMaxGameY=11000`.

### Tier 1: optional gameplay feel (after real height works)

- Fall damage / stamina at altitude
- Fog / snow biomes at high real Y
- Map FOW for peaks

Does not replace expand or invent compress curves for the planet.

### Tier 2: YDim expand details

**Purpose:** change the **game engine** so columns can be taller than 256, enabling true **1 m = 1 block** mountains (Everest ~8949). Remapping data alone is not enough.

Tall 1:1 columns are a **RealEarth feature**, not a third-party tool. The patcher ships in `Mods/RealEarth/Tools/` and as `make engine-expand`.

```bash
make install-full
make engine-expand
Mods/RealEarth/Tools/apply_engine_expand.sh
make install-height-500
make dedicated-height-test
make engine-restore
```

**Everest-scale:** YDim=**16384**, layers=**4096**, `EngineMaxGameY` ≤ **11000**. Does **not** expand XZ maps.

### Opt-in only: stock compress (not product)

`EngineHeightStockSafe=true` on an unexpanded engine compresses into **~0-250** so the mod can load without expand. Defaults are **false**. Do not document or ship this as the RealEarth experience. See [MODLET.md](MODLET.md).

**Host fold:** pack tiling for large host chunk coords. Dedicated does **not** pause when empty.

### Tier 2b: data / policy foundation (always on with the mod)

**Stock vs expanded (measured on V3.1.0 b14; values identical to the earlier V3.0.1 measurements):** see workspace [`7dtd-research/docs/terrain-height.md`](../../7dtd-research/docs/terrain-height.md).

| Constant | Stock | After RealEarth expand |
|---|---:|---:|
| `ChunkBlockYDim` | **256** | **16384** |
| `ChunkBlockYPow` | 8 | 14 |
| `ChunkBlockLayers` × `LayerHeight` | 64 × 4 | 4096 × 4 |
| `cMaxHeight` | **255** | **16383** |
| `ChunkAreaDim` (XZ 16×16) | **256** | **256** (must stay) |
| `Chunk.GetTerrainHeight` return | **byte** | **byte** (still lossy for peaks) |

These are **compile-time literals** (inlined as `ldc` in IL). `Field.SetValue` cannot raise the ceiling. Steam Verify restores stock; re-run `make engine-expand`.

RealEarth ships an **engine-height module** under `Source/RealEarth/EngineHeight/`:

| Piece | Role |
|---|---|
| `WorldConstantsProbe` | Read live YDim / layers at mod init |
| `AbsoluteHeightStore` | Sparse real-meter surfaces (sectioned columns) |
| `EngineHeightPolicy` | Single compress ceiling for inject |
| `EngineHeightMod` | Init + sample path used by `ChunkTerrainSampler` |

Config (`realearth.json`):

```json
"EnableEngineHeightMod": true,
"EngineMaxGameY": 11000,
"EngineHeightOneToOne": true,
"EngineHeightPreferVanillaCeiling": false
```

| Knob | Default | Meaning |
|---|---|---|
| `EngineMaxGameY` | **11000** | sea(100) + Everest(8849) + ~2 km fly-over air |
| `EngineHeightOneToOne` | **true** | `gameY = seaLevelY + elev_m` (1 m ≈ 1 block) |
| `EngineHeightPreferVanillaCeiling` | false | If true, clamp back to ~255 for legacy short columns |

- **Height mod math:** full int surfaces (`SampleGameHeightInt`, `AbsoluteHeightStore`); `gameY = seaLevelY(100) + elev_m`.
- **Stock storage:** columns **256** tall until expand. **Product:** `make engine-expand` → YDim **16384**, layers **4096** (Measured on expanded installs).
- **Residual after expand:** `Chunk`/`World.GetTerrainHeight` still return **byte** (lossy). Drive float/int queries + block/density inject. Long-term RAM: sparse Y sections ([`DYNAMIC_CHUNK_HEIGHT.md`](DYNAMIC_CHUNK_HEIGHT.md)).

Audit anytime:

```bash
cd tools && uv run python -m realearth.cli engine-audit
# or workspace RE:
# mono 7dtd-optimizer/tools/DumpTerrain.exe $ASM 7dtd-research/il/terrain-VERSION
```

If you only raise YDim to **1024** (staging), Everest still will not fit as true 1:1 (needs sea+8849 ≈ 8949). Product expand target is **16384** with `one_to_one` mapping, not a global compress curve.

### Tier 3: full 1:1 vertical (unlikely on stock Unity voxel stack)

Would approach a custom voxel engine or a game designed for huge Y (Minecraft-style multi-section columns). Not a small 7DTD modlet.

## Practical mapping for RealEarth

Keep storing **real meters** in `.rte` tiles (`elevation_m`). Compress only when writing:

- `dtm.raw` / game terrain 
- Runtime inject 

That way if a future height-limit mod lands, you **re-export** with a taller `max_y` without re-downloading DEM.

```text
.rte elevation_m → compress_elevation(max_y=250) → dtm / chunks
 → compress_elevation(max_y=1000) → future tall build
```

## Config knobs (current)

| Knob | Where | Meaning |
|---|---|---|
| `SeaLevelGameY` | `realearth.json` / bake | Game Y of sea surface (config default **100**; deep ocean is not a survival target). `bake-world` writes **32** unless `--sea-level` is passed, and the world manifest overrides the runtime config at init |
| `regional_exaggeration` | `height.compress_elevation` | Local relief boost |
| `max_y` | compress API | Ceiling (default 250) |

## Dynamic height (not just a taller static slab)

Raising 255 → 4096 **for every column** still wastes RAM on air over oceans and plains.

The right long-term model matches **dynamic XZ loading**:

- Columns are **sparse in Y**: only allocate height **sections** that contain terrain/builds.
- Stream Y sections near the player (surface ± dig/build margin), same as streaming XZ chunks.
- `.rte` keeps real meters; inject creates sections up to the DEM surface.

Full design: **[`DYNAMIC_CHUNK_HEIGHT.md`](DYNAMIC_CHUNK_HEIGHT.md)**.

## Bottom line

| Goal | Approach |
|---|---|
| Real mountain shape at true meters | **YDim expand + 1:1 inject** (product path) |
| Everest-scale absolute meters | Expand YDim **16384** + `gameY = sea + elev_m` |
| Stock / experiment only | Opt-in `EngineHeightStockSafe` compress (not ship) |
| Planet-scale RAM for tall columns | Near term: accept expand cost near players; long term: sparse Y ([DYNAMIC_CHUNK_HEIGHT](DYNAMIC_CHUNK_HEIGHT.md)) |
| Horizontal continuous Earth | Absolute XZ stream ([ABSOLUTE_STREAMING](ABSOLUTE_STREAMING.md)); orthogonal to vertical expand |

**Product rule:** keep **true meters in tiles**; expand is **required** for 1:1 height, not optional. Horizontal Streamed work still needs expand if mountains claim real elev_m. Status of inject/expand: [MODIFICATIONS](MODIFICATIONS.md). Engine sites: [realearth-surfaces](realearth-surfaces.md) §7. Generic constants: [research terrain-height](../../7dtd-research/docs/terrain-height.md).

## Related docs

| Doc | Role |
|---|---|
| [ENGINE_LIMITATIONS](ENGINE_LIMITATIONS.md) | Stock vertical blockers |
| [MODIFICATIONS](MODIFICATIONS.md) | Expand + inject status |
| [realearth-surfaces](realearth-surfaces.md) | Save-64, light 255, GetBlock index |
| [realearth-runtime](realearth-runtime.md) | Tall crust / inject gate lessons |
| [DYNAMIC_CHUNK_HEIGHT](DYNAMIC_CHUNK_HEIGHT.md) | Sparse Y future |
| [research terrain-height](../../7dtd-research/docs/terrain-height.md) | Stock vs expand IL constants |

## Changelog

- **2026-07-18:** Bottom line aligned with product expand-required policy; related docs; ownership header.
