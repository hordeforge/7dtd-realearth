# realearth-tools

Offline pipeline for RealEarth. Python **3.11+**, managed with **`uv` only**
(never pip / break-system-packages).

```bash
# from tools/
uv sync --extra dev
uv run realearth --help
uv run realearth demo --out ../data/samples/demo_region
```

From the repo root, prefer Makefile targets:

```bash
make setup
make demo
make test
```

Optional GIS stack (GeoTIFF DEM ingest):

```bash
uv sync --extra gis --extra dev
```

Optional engine audit (`realearth engine-audit` against a live
Assembly-CSharp.dll; without it the audit uses documented 3.0.1 defaults):

```bash
uv sync --extra audit --extra dev
```

Tests:

```bash
uv run --extra dev python -m pytest
# or: make -C .. test
```

## What the package does

The `realearth` command converts geographic inputs into versioned `.rte` tile
packs, exports 7DTD-compatible height/biome images, bakes bounded worlds, and
prepares mosaics for the browser viewer. It also contains coordinate, longitude
wrapping, local-window, height-model, and engine-audit utilities used by the C#
runtime project.

Run `uv run realearth --help` and `uv run realearth COMMAND --help` for the
authoritative option list. Common entry points:

```bash
uv run realearth info
uv run realearth demo --out ../data/samples/demo_region
uv run realearth build-region --help
uv run realearth inspect-tile ../data/samples/demo_region TX TZ
uv run realearth bake-world --help
uv run realearth export-viewer --help
uv run realearth serve --port 8765 --root ../viewer
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
