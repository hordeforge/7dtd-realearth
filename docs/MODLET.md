# RealEarth install (mod + YDim expand)

**Owns:** install steps, expand Tools/, shipped config keys.  
**Not:** architecture ([DESIGN](../DESIGN.md)), gap research ([GAP](GAP_HARMONY_MODLETS.md)), product status tables ([MODIFICATIONS](MODIFICATIONS.md)), Streamed deep-dive ([realearth-runtime](realearth-runtime.md)).  
**Hub:** [INDEX](INDEX.md).

RealEarth is a **C# mod** (`IModApi` + Harmony) **plus** engine **YDim expand** (part of this project). Product height is **real meters** (1 m = 1 block). Details: [HEIGHT_LIMITS](HEIGHT_LIMITS.md).

## Product pieces

| Piece | Role |
|--------|------|
| `RealEarth.dll` + `IModApi` | Config, tiles, streamer, session |
| Harmony hooks | Height queries, terrain inject |
| **YDim expand** (`EngineHeightPatcher`) | Raises `Assembly-CSharp` vertical limits (YDim=16384) |
| `.rte` / bake data | Real elevation packs |

Requires game **`0_TFP_Harmony`**. Do not ship a second Harmony.

## Full RealEarth (recommended)

Game **closed**. From repo:

```bash
make install-full # engine-expand + build + install (Streamed)
# or step by step:
make engine-expand # patches client + dedicated Assembly-CSharp
make install
./scripts/install_height_pack.sh h500 # or everest
```

From an installed mod folder (after `make package`):

```text
Mods/RealEarth/
 RealEarth.dll
 Config/realearth.json
 Tools/
 EngineHeightPatcher.exe
 Mono.Cecil.dll
 apply_engine_expand.sh # patches client (+ dedicated if present)
```

```bash
# Close 7DTD first
Mods/RealEarth/Tools/apply_engine_expand.sh
# restart game - log should show YDim=16384 / ENGINE EXPANDED
```

Restore stock DLLs: `make engine-restore` or Steam Verify (then re-run expand after updates).

## Without expand (not product)

Default config keeps **real-height mode** (`EngineHeightStockSafe=false`, `EngineHeightOneToOne=true`). On a stock engine the log tells you to run expand; tall columns are not playable until YDim is raised.

Optional experiment only: set `EngineHeightStockSafe=true` to compress into ~0-250 so the world loads without expand. That is **not** the product path and is off by default.

| | Stock engine | With RealEarth YDim expand |
|--|----------------|----------------------------|
| Streamed tiles / fold | Yes | Yes |
| Inject / Harmony | Real meters (needs expand for tall mesh) | Real meters 1:1 up to content maxY |
| Everest-scale mesh | No | Yes (YDim=16384, maxGameY≤11000) |

## Config

- Default `Config/realearth.json`: real height (`EngineHeightStockSafe=false`, `EngineHeightOneToOne=true`). Use `make install-full`.
- `Config/realearth.advanced_height.json`: tall-profile template (Everest spawn; same policy).

## Debug map FOW (config keys)

| Key | Default | Meaning |
|---|---|---|
| `DebugRevealFullMap` | `true` | Fill FOW for host extent once after load |
| `DebugMapRevealRadiusChunks` | `128` | ~2048 m radius around player (tracks travel) |

F1: `rereveal`. Set both off for production-like FOW.

## City names (config keys)

Behavior and data: **[CITY_MAP_LABELS.md](CITY_MAP_LABELS.md)** (edge unlock, center pin, `edge_radius_m`).

| Key | Default | Meaning |
|---|---|---|
| `ShowCityNamesOnMap` | `true` | Discover place names as map NavObjects |
| `CityMapMaxLabels` | `250` | Cap on discovered labels |
| `CityMapMinPopulation` | `0` | Min population filter |
| `CityMapDiscoverRadiusScale` | `1.0` | Multiplier on map-derived edge radius |

F1: `recities` / `recities reset` / `recities here`. XML: `Config/nav_objects.xml` class `realearth_city`.

## Related docs

| Doc | Role |
|---|---|
| [PROTON_INSTALL](PROTON_INSTALL.md) | Proton GeneratedWorlds paths |
| [HEIGHT_LIMITS](HEIGHT_LIMITS.md) | Expand required |
| [GAME_VERSION](GAME_VERSION.md) | V3.1.0 pin |
| [SINGLE_WORLD](SINGLE_WORLD.md) | Baked vs Streamed |
| [MODIFICATIONS](MODIFICATIONS.md) | Status |

## Changelog

- **2026-07-19:** Related docs.
