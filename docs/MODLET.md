# RealEarth install (mod + YDim expand)

**Owns:** install steps, expand verification (runtime hot-patch, no separate step), shipped config keys.  
**Not:** architecture ([DESIGN](../DESIGN.md)), gap research ([GAP](GAP_HARMONY_MODLETS.md)), product status tables ([MODIFICATIONS](MODIFICATIONS.md)), Streamed deep-dive ([realearth-runtime](realearth-runtime.md)).  
**Hub:** [INDEX](INDEX.md).

RealEarth is a **C# mod** (`IModApi` + Harmony) **plus** engine **YDim expand** (part of this project). Product height is **real meters** (1 m = 1 block). Details: [HEIGHT_LIMITS](HEIGHT_LIMITS.md).

## Product pieces

| Piece | Role |
|--------|------|
| `RealEarth.dll` + `IModApi` | Config, tiles, streamer, session |
| Harmony hooks | Height queries, terrain inject |
| **YDim expand** (runtime transpiler) | Raises `Assembly-CSharp` vertical limits at boot (YDim=32768) |
| `.rte` / bake data | Real elevation packs |

Requires game **`0_TFP_Harmony`**. Do not ship a second Harmony.

## Full RealEarth (recommended)

Game **closed**. From repo:

```bash
make install  # product: hot-patches the YDim expand at boot (default)
./scripts/install_height_pack.sh h500 # or everest
```

The default `EngineHeightRuntimePatch=true` rewrites the YDim literals at
runtime via Harmony transpilers when the engine is stock (validated live). No
DLL is edited and nothing needs re-applying after Steam Verify.

From an installed mod folder (after `make package`):

```text
Mods/RealEarth/
 RealEarth.dll
 Config/realearth.json
```

The mod hot-patches the YDim expand at boot; no Tools/ step is needed. The
log should show `YDim=32768 / ENGINE EXPANDED`.

## Without expand (not product)

Default config keeps **real-height mode** (`EngineHeightStockSafe=false`, `EngineHeightOneToOne=true`, `EngineHeightRuntimePatch=true`). On a stock engine the mod hot-patches the YDim expand at boot; if that is disabled, the log says so.

Optional experiment only: set `EngineHeightStockSafe=true` to compress into ~0-250 so the world loads without expand. That is **not** the product path and is off by default.

| | Stock engine | With RealEarth YDim expand |
|--|----------------|----------------------------|
| Streamed tiles / fold | Yes | Yes |
| Inject / Harmony | Real meters (needs expand for tall mesh) | Real meters 1:1 up to content maxY |
| Everest-scale mesh | No | Yes (YDim=32768, maxGameY≤29000) |

## Config

- Default `Config/realearth.json`: real height (`EngineHeightStockSafe=false`, `EngineHeightOneToOne=true`). `make install` keeps the shipped defaults.
- `Config/realearth.advanced_height.json`: tall-profile template (Everest spawn; dev FOW on).

At init the mod validates the config and logs one `[RealEarth] config:` line per issue,
clamping out-of-range numbers to safe values (unknown `MapMode` behaves as Streamed).
Install/package scripts (`make install`, `make package`) reject `MAP_MODE` values other
than `Streamed|Baked`.

### Environment variables (install + dedicated helpers)

All optional; defaults shown. Scripts fail fast when numeric values are invalid.

| Variable | Default | Used by |
|---|---|---|
| `SEVENDTD_GAME_DIR` | Steam client path | install/expand/package, and the `main.ttw` template lookup on bake. Set either this or the make knob `GAME_DIR`; an explicit `make install GAME_DIR=...` exports it |
| `SEVENDTD_SERVER_DIR` | Dedicated server path | dedicated start/expand/install helpers, and the `main.ttw` template lookup on bake |
| `STEAM_DIR` | `~/.local/share/Steam` | Steam root discovery: Proton userdata, generated-world install targets, client log scan |
| `MAP_MODE` / `GAME_DIR` | `Streamed` / Steam path | `make install*`; only `Streamed\\|Baked` accepted |
| `DOTNET_ROOT` | auto-detected local SDK caches | build + scripts |
| `RE_DEDICATED_USERDATA` | `~/.cache/realearth-dedicated` | dedicated helpers |
| `RE_WORLD_NAME` | script default (`RealEarth_H500`, `RWG`, `Navezgane`) | dedicated helpers |
| `RE_WORLD_GEN_SIZE` / `RE_WORLD_GEN_SEED` | `4096` / `botpoi4k` | `start_dedicated_prefab.sh` |
| `RE_GAME_NAME` | `BotPoi_<world>_<size>` | dedicated helpers |
| `RE_SERVER_MAX_PLAYERS` | `1024` (height test) / `64` (prefab) | serverconfig injection |
| `RE_SERVER_WAIT` / `RE_SERVER_SOAK` | `180` / `35` seconds | `run_dedicated_height_test.sh` |
| `RE_SCRATCH` / `RE_LOADTEST_ROOT` | unset / `../7dtd-loadgen` | load-test wiring |
| `RE_TERRARIUM_CACHE` | unset (no caching) / `<repo>/data/cache/terrarium` via make | offline tile cache for the Python pipeline (`tools`) |
| `RE_SAVE_TRASH_DAYS` | `7` | `run_dedicated_height_test.sh` save-trash window |
| `STEAM_DIR` | auto-detect | `tools/` Proton path resolution |
| `RE_ROOT` | repo root | `backup_artifacts.sh`; operate on another tree instead of this checkout |
| `RE_VIEWER_SMOKE_PORT` | `8765` | `test-viewer-smoke.sh`; set when 8765 is already taken |

### Main keys

| Key | Default | Valid values / meaning |
|---|---|---|
| `MapMode` | `Streamed` | `Streamed` (sliding window over full Earth) or `Baked` (one finite DTM world) |
| `MultiplayerOriginMode` | `SoloSlide` | `SoloSlide` (planetary travel), `SharedFixed` (co-located MP combat); `SharedSlide` is accepted and normalizes to `SoloSlide` |
| `TilePackPath` | `Data/tiles` | Pack dir with `.rte` tiles (+ optional `earth.manifest.json`) |
| `WorldWidth` / `WorldHeight` | full planet | Host canvas extent; regional packs override via manifest |
| `TileSize` | `512` | `.rte` tile edge in blocks |
| `StreamRadiusTiles` / `UnloadRadiusTiles` | `2` / `4` | Per-player tile bubble; unload must exceed stream radius |
| `LocalWindowSize` | `1024` | Finite host window; clamped to pack extent at init |
| `EnableLongitudeWrap` | `false` (auto `true`) | Antimeridian wrap. `Validate()` auto-enables for Streamed + `WorldWidth>=40000000` + no regional bbox; keep false for Baked / regional packs |
| `SeaLevelGameY` | `16000` | Game Y of sea surface (anchored for real depth below sea) |
| `FailClosedMissingTiles` | `true` | Log (and refuse to invent) missing DEM tiles |
| `EnableEngineHeightMod` | `true` | Height sampling/inject for Streamed packs |
| `EngineHeightStockSafe` | `false` | Opt-in compress for stock engines; **not** product path |
| `EngineMaxGameY` | `29000` | 1:1 ceiling (sea + airliner cruise + headroom) after expand |
| `SpawnLongitude` / `SpawnLatitude` | `0` | Degrees; `0,0` falls back to `DefaultSpawn*` |
| `DefaultSpawnLon` / `DefaultSpawnLat` | `-104.9903` / `39.7392` (Denver) | Degrees; used when `SpawnLongitude`/`SpawnLatitude` are `0,0`. `mod_config --spawn-from-bbox` overwrites them with the pack bbox centre |
| `EnableRuntimePoiInject` | `true` | Stamp prefabs and POIs on the real surface at runtime (`RuntimePoiInject`) |
| `RuntimePoiMaxPerArea` | `80` | Density cap per area; clamped at inject time to the hard cap 80 (`DensityBudget.DefaultMaxPrefabsPerKm2`) |

## Debug map FOW (config keys)

Shipped configs keep both off (`Config/realearth.advanced_height.json` is the dev template).

| Key | Default | Meaning |
|---|---|---|
| `DebugRevealFullMap` | `false` | Fill FOW for host extent once after load (dev: `true`) |
| `DebugMapRevealRadiusChunks` | `0` (off) | ~2048 m radius around player, tracks travel (dev: `128`) |

F1: `rereveal`.

## City names (config keys)

Behavior and data: **[CITY_MAP_LABELS.md](CITY_MAP_LABELS.md)** (edge unlock, center pin, `edge_radius_m`).

| Key | Default | Meaning |
|---|---|---|
| `ShowCityNamesOnMap` | `true` | Discover place names as map NavObjects |
| `CityMapMaxLabels` | `250` | Cap on discovered labels |
| `CityMapMinPopulation` | `0` | Min population filter |
| `CityMapDiscoverRadiusScale` | `1.0` | Multiplier on map-derived edge radius |

F1: `recities` / `recities reset` / `recities here`. XML: `Config/nav_objects.xml` class `realearth_city`.

Spawn pressure: `Config/spawning.xml` raises commercial/downtown `maxcount` for pine/burnt/desert/wasteland (Sandbox Enemy Density = Default only). Gamestage soft nudge: `Config/gamestages.xml` sets `difficultyBonus` 1.2→1.35.

Altitude climate (`LandcoverTempOffsetC` on ambient): `Config/buffs.xml` hypoxia/cold buffs driven by player-tick elev ASL + lat ISA lapse (`AltitudeClimate` / `AltitudeClimateTick`).

F1 lon/lat: `relonlat` / `rll` (optional `<x> <z>`) prints local XZ → Earth blocks → lon/lat.

Fall / spawn Y (soft): `SnapSpawnToSurface` (default true) + `FallDamageModifierScale` (default 0.35) via `FallSpawnRetune`.

Production FOW (soft): `MapExploreRevealRadiusChunks` (default 8) via `MapReveal`; debug full-map knobs unchanged.

## Related docs

| Doc | Role |
|---|---|
| [PROTON_INSTALL](PROTON_INSTALL.md) | Proton GeneratedWorlds paths |
| [HEIGHT_LIMITS](HEIGHT_LIMITS.md) | Expand required |
| [GAME_VERSION](GAME_VERSION.md) | V3.2.0 pin |
| [SINGLE_WORLD](SINGLE_WORLD.md) | Baked vs Streamed |
| [MODIFICATIONS](MODIFICATIONS.md) | Status |

## Changelog

- **2026-08-23:** Config key reference + env-var table; FOW defaults corrected to shipped values (`false`/`0`); startup validation documented.
- **2026-07-19:** Related docs.
