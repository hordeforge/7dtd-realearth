# 🌍 Pangea (RealEarth 1:1 Engine)

> **Part of [HordeForge](https://github.com/hordeforge)**: High-Performance Systems Engineering for 7 Days to Die.

![CI](https://github.com/hordeforge/7dtd-realearth/actions/workflows/ci.yml/badge.svg)
![coverage](https://raw.githubusercontent.com/hordeforge/7dtd-realearth/badges/coverage.svg)
![license](https://img.shields.io/github/license/hordeforge/7dtd-realearth)
![release](https://img.shields.io/github/v/release/hordeforge/7dtd-realearth)
![languages](https://img.shields.io/github/languages/count/hordeforge/7dtd-realearth)
![top language](https://img.shields.io/github/languages/top/hordeforge/7dtd-realearth)

A **1:1 scale real-world Earth** project for **7 Days to Die V3.1.0** (Henpocalypse): real elevation, landcover heuristics, city/population density, tile streaming, longitude wrap (circle the planet), and a globe-style world map.

This is **not** a single giant heightmap. Earth at 1 block = 1 m is ~40,075 km wide. Vanilla maps top out around 8–16 km. RealEarth uses **offline tile packs** + a **Harmony runtime** that streams only what is near the player.

**Docs:** [INDEX](docs/INDEX.md) (hub) · [DESIGN](DESIGN.md) (architecture) · [MODLET](docs/MODLET.md) (install + expand) · [CHANGELOG](CHANGELOG.md) (what changed per release) · [TODO](TODO.md) (backlog)

Debug FOW / city names: see [MODLET](docs/MODLET.md) config keys (details in [CITY_MAP_LABELS](docs/CITY_MAP_LABELS.md)).

## What you get today

| Piece | Status |
|---|---|
| Design + coordinate system (wrap, tiles) | Done |
| Offline Python pipeline (`.rte` tiles, heightmaps, biomes) | Done |
| Demo region builder (synthetic or Open-Meteo DEM) | Done |
| Settlement/population stamping plan | Done |
| **Web map viewer** (flat + globe) | Done |
| **One continuous in-game map** (Baked bake-world + Streamed session) | Done (Baked fully playable; Streamed hooks need live retarget) |
| C# WorldSession + streamer + runtime Harmony discovery | Done |
| Per-build terrain density inject | Needs your 3.1.0 `Assembly-CSharp` retarget |
| Full-planet tile farm | Pipeline-ready; data download is on you |

**In-game as one large map:** see [docs/SINGLE_WORLD.md](docs/SINGLE_WORLD.md).

## Makefile (recommended)

```bash
make help # list targets
make setup # uv sync tools + check game path
make test # Python tests
make build # RealEarth.dll
make install-full # YDim expand (part of RealEarth) + mod install
make install # mod only (still need expand for real height)
make package # dist/RealEarth (+ Tools/ expand)
make install-height-500 # staged H500 pack
make engine-expand # YDim expand alone (client + dedicated)
make dedicated-height-test # SharedFixed MP config + YDim soak
make test-mp # multiplayer origin/bubble unit tests
make check
```

**Load-test bots** (LiteNetLib join/wander/death/respawn) live in the sibling project
[`../7dtd-loadgen`](../7dtd-loadgen) (`make -C ../7dtd-loadgen help`).

Overrides: `make install MAP_MODE=Baked GAME_DIR=... DOTNET_ROOT=...` 
Tools-only: `make -C tools help`

## Quick start: generate a playable region heightmap

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
make setup && make demo # or manually below

cd tools
uv sync --extra dev

# Offline demo (no network): Denver-sized synthetic pack
uv run python -m realearth.cli demo --out ../data/samples/demo_region

# Web map viewer (flat pan/zoom + 3D globe)
make -C .. viewer && make -C .. serve
# or: realearth export-viewer / realearth serve
# → http://127.0.0.1:8765/

# ONE continuous in-game map (Baked, up to 16k) - single save, edge-to-edge
# writes a GeneratedWorlds folder (dtm.raw + biomes.png + map_info.xml);
# copy it into ~/.local/share/7DaysToDie/GeneratedWorlds and start a new game
realearth bake-world --pack ../data/samples/demo_region --size 8192 --out ../worlds/RealEarth_8k
# PNG-only output for a custom heightmap importer: add --heightmap-only

# Or real elevation for a small bbox (network, rate-limited)
realearth build-region \
 --west -105.3 --south 39.5 --east -104.7 --north 40.0 \
 --source open_meteo \
 --resolution 90 \
 --out ../data/samples/denver_real
```

Viewer details: [viewer/README.md](viewer/README.md).

Outputs:

```
data/samples/demo_region/
 earth.manifest.json
 tiles/{z}/{x}.rte
 settlements.json
 export_7dtd/
  heightmap.png # 16-bit for custom heightmap importers
  biomes.png
  preview.png
  export_meta.json
```

### Install heightmap into 7DTD (Phase 0 path)

1. Install a **custom heightmap importer** mod for your game version (e.g. Nexus “Custom Height Map Importer” for 2.5, or equivalent).
2. Copy `export_7dtd/heightmap.png` as that mod expects (often `heightmap.png` next to its config).
3. Remap `biomes.png` colors if your game’s biome palette differs (see `tools/realearth/landcover.py`).
4. Generate the world in-game.

Product height is **real meters** (seaLevelY + elev_m) after **YDim expand**. Stock engines alone are ~0-255 and are not the ship path. Sea level defaults to game Y=100 (shallow ocean floor; players will not survive deep underwater).

## Full Earth / streaming mode (Phase 2+)

1. Build tile packs with `realearth build-region` or a planet-scale farm using absolute indices from `realearth planet-tiles`.
2. Build the C# mod against your game:

```bash
export SEVENDTD_GAME_DIR="/path/to/7 Days To Die"
dotnet build Source/RealEarth/RealEarth.csproj -c Release -p:GameDir="$SEVENDTD_GAME_DIR"
```

3. Install (same layout as [7daystodiemods.com](https://7daystodiemods.com/posts/how-to-install-7-days-to-die-mods) guides):

```
7DaysToDie/Mods/RealEarth/ # ModInfo.xml must be directly here (no extra nest)
 ModInfo.xml
 Config/realearth.json
 RealEarth.dll # build output
 Data/tiles/ # your tile pack (manifest + tiles/)
```

Do **not** delete `Mods/0_TFP_Harmony/` (vanilla; required for C# mods).

4. Configure `Config/realearth.json`:

- `TilePackPath` – local tiles
- `TileCdnBaseUrl` – optional HTTP base for missing tiles (`{base}/tiles/{tz}/{tx}.rte`)
- `EnableLongitudeWrap` – circle the Earth on X
- `StreamRadiusTiles` / `UnloadRadiusTiles` - memory vs pop-in (shipped default 2 / 4)
- `LocalWindowSize` – sliding host canvas (default **1024**; not fully meshed - view distance is smaller)
- `MultiplayerOriginMode` – `SoloSlide` (window follows you) / `SharedFixed` (MP freeze)

**Important:** Harmony method names change every major 7DTD update. `HarmonyBootstrap` loads patches from the assembly; concrete `[HarmonyPatch]` targets must be filled in for your `Assembly-CSharp.dll` (search chunk terrain generation). Until then, use the heightmap export path.

## CLI reference

```bash
realearth info
realearth lonlat -74.006 40.7128 # NYC → block/tile
realearth wrap-check 40075020 # antimeridian wrap
realearth demo [--source synthetic|open_meteo]
realearth build-region --west … --south … --east … --north … --out DIR
realearth bake-world --pack DIR --size 8192 --out worlds/NAME # one continuous map
realearth export-viewer --pack DIR --out viewer/data/NAME
realearth serve
realearth list-tiles DIR
realearth inspect-tile DIR TX TZ
realearth planet-tiles --west … --south … --east … --north …
```

## One large map in the game

RealEarth is designed as **one world / one save**, not multiple maps.

| Mode | Config | How to play |
|---|---|---|
| **Baked** | `MapMode: Baked` | `bake-world` → heightmap importer → start one new game on that world |
| **Streamed** | `MapMode: Streamed` (default) | Generate one host world (8k/16k), install mod + tiles, travel continuously with sliding window + wrap |

```bash
realearth bake-world --pack data/samples/demo_region --size 8192 --out worlds/RealEarth_8k
```

Details: [docs/SINGLE_WORLD.md](docs/SINGLE_WORLD.md). Engine max for a loaded mesh is ~**16384** blocks; full Earth 1:1 uses Streamed mode.

## Cities and density

- Built-in seed cities (approx coordinates + population) drive demo density blobs and POI plans inside `.rte` tiles.
- Pass `--settlements places.geojson` with Point features and `name` / `population` properties for real datasets (Natural Earth, GeoNames exports, etc.).
- Population channel is log-scaled 0–255; high values mark **URBAN** landcover and select prefab packs (`metro` → `hamlet`).

## Globe minimap

Runtime state lives in `GlobeMapState` / `GlobeMapFrame`:

- Sphere projection for a true globe UI
- Equirectangular UV fallback (flat map that wraps)
- Local radar remains the short-range minimap; globe is the planetary view

Wire to Unity IMGUI/UI once Harmony UI patches are in place. Toggle design intent: open globe map key → show planet + player lon/lat + discovered cities. In-game map names already use edge discovery (see [docs/CITY_MAP_LABELS.md](docs/CITY_MAP_LABELS.md)).

## What “1:1” means

Horizontal and vertical 1 m/block (expand required for height); planet is virtual (stream tiles); buildings are density stamps, not cadastral meshes. Full definition: [DESIGN](DESIGN.md).

## Honest limits (summary)

Planet cannot load as one mesh; Streamed inject needs live retarget; tall Y needs expand; lon/lat is equirectangular (high-lat distortion). Details: [ENGINE_LIMITATIONS](docs/ENGINE_LIMITATIONS.md), [LON_LAT](docs/LON_LAT.md), [GAP](docs/GAP_HARMONY_MODLETS.md). Ideas: [DESIGN §18](DESIGN.md). Status: [MODIFICATIONS](docs/MODIFICATIONS.md) · [TODO](TODO.md).

## Configuration profiles

The files under `Config/` are examples for different operating modes:

| File | Intended use |
|---|---|
| `realearth.json` | Default runtime configuration |
| `realearth.mp.json` | Shared-fixed multiplayer streaming profile |
| `realearth.advanced_height.json` | Expanded-height experiments |
| `biomes.xml` / `rwgmixer.xml` | Game-side biome and RWG integration |

Keep the exact installed configuration with test notes. In multiplayer, every
participant must agree on the world/session coordinate model and required data;
do not switch origin mode on an existing save without understanding the save and
delta implications described in `docs/MULTIPLAYER_STREAMING.md`.

## Verification and troubleshooting

```bash
make info # show resolved paths and tool versions
make test-fast # coordinate, height, and tile smoke tests
make test-mp # multiplayer window/origin model tests
make build # compile against the selected game installation
make check # setup, fast tests, python + shell + TS + HTML lint gates, NPI and mod build
```

If the mod does not load, first confirm that `ModInfo.xml` is directly under
`Mods/RealEarth`, the DLL was built against the installed game assemblies, and
`0_TFP_Harmony` is still present. If terrain is flat or clipped, distinguish a
missing tile/configuration problem from the stock vertical ceiling; use
`reheight`, the server log, and `make engine-audit` before regenerating data.

Viewer failures are usually caused by opening `index.html` through `file://` or
by a stale/missing exported pack. Serve it over HTTP and re-run `make viewer`.

## Generated data and backups

Tile packs, viewer mosaics, baked worlds, build output, and packaged mods are
generated artifacts and may be large. Retain their manifest/export metadata so
the source bounds, resolution, coordinate assumptions, and elevation provider
remain traceable. Before `make engine-expand`, close both client and dedicated
server and preserve the stock assembly backup. Steam updates or verification
can replace patched assemblies, so audit and reapply deliberately afterward.

## Contributing

Keep Python pipeline changes deterministic and cover coordinate, wrapping,
height, and tile-format behavior with tests under `tools/tests/`. C# Harmony
changes must be checked against the exact supported 7DTD build. Avoid committing
third-party geodata unless its license and redistribution terms are documented
in [`ATTRIBUTION.md`](ATTRIBUTION.md).

See [`TODO.md`](TODO.md) for the current runtime, height, data, viewer, and
release backlog.

## License

Code in this repository is licensed under the MIT License ([`LICENSE`](LICENSE)).
Third-party geodata: see ATTRIBUTION.md; you are responsible for compliance.
