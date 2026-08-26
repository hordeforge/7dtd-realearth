# realearth-tools

Offline pipeline for RealEarth. Python **3.11+**, managed with **`uv` only**
(never pip / break-system-packages).

```bash
# from tools/
uv sync --locked --extra dev
uv run --locked realearth --help
uv run --locked realearth demo --out ../data/samples/demo_region
```

Every command below uses `--locked`: when pyproject.toml drifts from uv.lock,
uv fails instead of silently re-resolving and rewriting the lockfile. A
dependency change is an explicit `uv lock` review, never a side effect of
running something.

From the repo root, prefer Makefile targets:

```bash
make setup
make demo
make test
```

Optional GIS stack (GeoTIFF DEM ingest):

```bash
uv sync --locked --extra gis --extra dev
```

Optional engine audit (`realearth engine-audit` against a live
Assembly-CSharp.dll; without it the audit uses documented 3.0.1 defaults):

```bash
uv sync --locked --extra audit --extra dev
```

Tests and gates:

```bash
uv run --locked --extra dev python -m pytest
make lint      # ruff check + black --check + mypy (strict)
# or from the repo root: make -C .. test && make -C .. lint
```

Two modules here are also called directly by the shell install scripts, so they
stay stdlib-only and run without uv:

```bash
PYTHONPATH=. python3 -m realearth.mod_config write DEST ROOT [KEY=VALUE ...]
PYTHONPATH=. python3 -m realearth.server_config SRC DEST [--userdata P] [NAME=VALUE ...]
PYTHONPATH=. python3 -m realearth.proton_paths
```

## What the package does

The `realearth` command converts geographic inputs into versioned `.rte` tile
packs, exports 7DTD-compatible height/biome images, bakes bounded worlds, and
prepares mosaics for the browser viewer. It also contains coordinate, longitude
wrapping, local-window, height-model, and engine-audit utilities used by the C#
runtime project.

Run `uv run --locked realearth --help` and
`uv run --locked realearth COMMAND --help` for the authoritative option list.
Common entry points:

```bash
uv run --locked realearth info
uv run --locked realearth demo --out ../data/samples/demo_region
uv run --locked realearth build-region --help
uv run --locked realearth inspect-tile ../data/samples/demo_region TX TZ
uv run --locked realearth bake-world --help
uv run --locked realearth export-viewer --help
uv run --locked realearth serve --port 8765 --root ../viewer
```

## Inputs and outputs

Region builds accept geographic bounds, an elevation source, resolution, and
optional settlement data. A pack normally contains `earth.manifest.json`,
`tiles/`, settlement metadata, and optional `export_7dtd/` images. Preserve the
manifest: it records the assumptions required to inspect, reproduce, or consume
the pack at runtime.

## Relation to the mod

This package is offline tooling. The in-game product is `Source/RealEarth` plus
optional YDim expand (`make engine-expand`). Load-test bots live in sibling
`../7dtd-loadgen`, not here.
