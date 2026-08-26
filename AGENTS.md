# AGENTS.md - 7dtd-realearth (RealEarth)

**1:1-scale real-world Earth** project for **7 Days to Die V3.1.0** (Henpocalypse):
elevation, landcover heuristics, density/cities, tile streaming, longitude wrap,
globe-style map, and optional **YDim expand**.

Not a general optimizer. Not an APM suite. Not the load generator (that moved to
sibling `7dtd-loadgen`).

Workspace root guide: [`hordeforge/.github` MODDING_BEST_PRACTICES.md](https://github.com/hordeforge/.github/blob/main/MODDING_BEST_PRACTICES.md)

## Scope

| Owns | Does not own |
|---|---|
| RealEarth C# mod (net48), streaming, height inject | EfficientServer-style AI/mesh optim |
| Offline Python tile pipeline (`tools/`) | Host APM collectors |
| YDim / engine expand tools (part of this product) | LiteNetLib bot clients (use `7dtd-loadgen`) |
| Bake-world / heightmap export / web viewer | Google bulk Earth data (disallowed; see docs) |
| Docs for realism, streaming, cities, Proton install | Silent patches into optimizer/APM repos |

## Critical rules

1. **Prefer Harmony over disk-patching `Assembly-CSharp`.** Engine expand is an explicit, exceptional path with backup/restore (`make engine-expand`, `make engine-restore`). Dry-run before write.
2. **Keep expand logic in RealEarth**, never in EfficientServer or APM.
3. **Data sources:** Copernicus / Terrarium / OSM-class sources only. Google Earth bulk data is not allowed (`docs/REALISM_AND_GOOGLE_EARTH.md`).
4. **Product height is real meters (1 m = 1 block).** YDim expand is required. Do not treat global compress (`EngineHeightStockSafe`) as the product path. See `docs/HEIGHT_LIMITS.md`.
5. **Retarget Managed refs after game updates** (client + dedicated). V3.1.0 publicizer rules: overrides of vanilla methods may need to be public.
6. **Python tooling: `uv` only** under `tools/`. Never pip / break-system-packages. Large scratch goes under project dirs or disk-backed cache, not tmpfs `/tmp`.
7. **Install can write into Steam game directories.** Stop the game/server, keep backups, and confirm `GAME_DIR` / `SEVENDTD_GAME_DIR` before `make install*` or expand.
8. **No AI attribution** in commits/docs/comments. **No em dashes** in shipped text.
9. **Load-test bots live in `../7dtd-loadgen`.** Do not reintroduce them under `tools/`.
   Client scenarios: `cd ../7dtd-loadgen && make scenarios` (see that project `docs/REALEARTH.md`).

## Build / install / test

```bash
make help
make setup                 # uv sync tools + check game path
make test                  # Python tests
make lint                  # Ruff + black --check (tools/, scripts/) + mypy (tools/realearth)
make test-mp               # multiplayer origin/bubble unit tests
make build                 # RealEarth.dll
make install               # mod only (still needs expand for real height)
make install-full          # YDim expand + mod install (product path)
make package               # dist/RealEarth (+ Tools/ expand)
make engine-expand         # YDim expand alone (client + dedicated)
make engine-expand-dry     # preview IL patches
make engine-restore        # restore stock Assembly-CSharp from backup
make demo                  # synthetic demo region pack
make viewer && make viewer-build && make serve  # web map viewer (TS sources)
make check
make clean
```

Overrides: `make install MAP_MODE=Baked GAME_DIR=... DOTNET_ROOT=...`.

Default client root:

```text
~/.local/share/Steam/steamapps/common/7 Days To Die
```

Dedicated is a separate Steam app; expand/install scripts may target both. Proton notes: `docs/PROTON_INSTALL.md`.

### Offline pipeline (uv)

```bash
cd tools && uv sync --locked --extra dev
uv run --locked python -m realearth.cli demo --out ../data/samples/demo_region
uv run --locked python -m realearth.cli bake-world --pack ../data/samples/demo_region \
  --size 8192 --out ../worlds/RealEarth_8k
```

## Docs ownership

| Tree | Owns |
|---|---|
| `docs/` (this project) | Product design, status, Streamed lessons (`realearth-runtime`, `realearth-surfaces`, `realearth-review`, MODIFICATIONS, LON_LAT, …) |
| `../7dtd-engine-research/docs/` | **Generic** dedicated engine RE only (loop, AI, net, save, terrain APIs). Not product status. |

Hub: [`docs/INDEX.md`](docs/INDEX.md) (ownership: install vs status vs gaps vs lon/lat). Do not re-list
every doc path in answers; point agents at INDEX + the owning file. Engine RE hub:
[`../7dtd-engine-research/docs/INDEX.md`](../7dtd-engine-research/docs/INDEX.md).

## Layout

```text
Source/RealEarth/   C# mod (net48 Harmony + streamer)
Config/             XML / modlet config
tools/              Python realearth pipeline (uv project)
scripts/            install, expand, dedicated helpers
docs/               product docs (RealEarth-owned narratives)
viewer/             web map (flat + globe)
webmod/             stock dashboard webui source (ts); built bundle under webmod/build/
data/               samples and generated packs (runtime artifacts)
worlds/             baked worlds (runtime artifacts)
DESIGN.md           architecture and phased delivery
```

## Sibling projects

| Project | Role |
|---|---|
| `../7dtd-loadgen` | Join bots / dedicated soak against RealEarth or stock worlds |
| `../7dtd-server-apm` | Measure streamer/height cost under load |
| `../7dtd-server-optimizer` | Unrelated dedicated optim product |

Do not silently couple RealEarth patches into EfficientServer or APM.

## Stock-game research -> 7dtd-engine-research

Anything that studies the **stock** dedicated server belongs in
[`../7dtd-engine-research/`](../7dtd-engine-research/), not here: reverse-engineering
narratives (`docs/`), the Mono.Cecil dump tooling (`tools/`), wire/protocol
analysis, and engine cost/loop RE. This repo owns the RealEarth terrain/streaming product;
it does not host stock-game RE docs or dumpers. When RE is needed, add it
under `../7dtd-engine-research/` and link back. How to RE:
[`../7dtd-engine-research/docs/re-methodology.md`](../7dtd-engine-research/docs/re-methodology.md).
