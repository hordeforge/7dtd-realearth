# RealEarth web map viewer

Browser UI for tile packs: **flat pan/zoom map** and **3D globe**, with elevation, land cover, population, and settlement layers.

## Quick start

From the repo (with tools installed):

```bash
# from repo root (or tools/)
make setup

# 1) Build a tile pack (if you do not already have one)
make demo
# or: cd tools && uv run --locked realearth demo --out ../data/samples/demo_region

# 2) Export viewer mosaics into viewer/data/demo
cd tools && uv run --locked realearth export-viewer \
  --pack ../data/samples/demo_region \
  --out ../viewer/data/demo

# 3) Serve the static site
uv run --locked realearth serve
# open http://127.0.0.1:8765/
# or from repo root: make serve
```

Optional query: `http://127.0.0.1:8765/?pack=data/demo`

## Features

| Feature | Description |
|---|---|
| Flat map | Pan, zoom, opacity, tile grid overlay |
| Globe | Three.js sphere mirroring the active layer; region packs are composited onto full Earth with a bbox highlight, auto-framed on entry |
| Globe navigation | Drag to orbit, scroll/pinch or `+/−` buttons to zoom, eased fly-to (`frameRegion`, jump targets), idle spin with pause-on-interaction and a Spin toggle |
| Layers | Hybrid, elevation (hillshade), land cover, population density |
| Settlements | Markers + hover tooltip from `settlements.json` |
| Probe | Lon/lat under cursor; approximate elevation from raw elev PNG |
| Player | Optional live marker + jump-to-player (button, `P` key, deep link, polled feed) |
| Multi-pack | `data/catalog.json` lists extra datasets |

## Player position

The viewer can show and jump to a live player position. Three entry points,
all optional and independent:

- **Feed file**: `viewer/data/player.json`, polled every 5 s:

  ```json
  { "name": "Maci", "lon": -104.99, "lat": 39.74 }
  ```

  Malformed or out-of-range fixes are ignored; an absent file just hides the
  marker. Anything that can write that file (a game mod hook, a script
  parsing the server log) moves the marker without a reload.
- **Deep link**: `?player=lat,lon` (Google-Maps-style lat first) seeds the
  jump inputs and flies there after the pack loads.
- **Manual**: the "Jump to lat, lon" inputs plus `Go`, or press `P` for the
  latest feed fix.

Jump works in both views: the flat map recenters, the globe flies an eased
great-circle hop to the target.

## Export layout

`realearth export-viewer` writes:

```
viewer/data/<name>/
  viewer.json          # metadata + layer list + bbox
  hybrid.png
  elevation.png
  landcover.png
  population.png
  elevation_raw.png    # for cursor elevation probe
  settlements.json     # optional copy
```

## Catalog (multiple packs)

Create `viewer/data/catalog.json`:

```json
[
  { "path": "data/demo", "name": "Demo Denver" },
  { "path": "data/europe", "name": "Europe 30m" }
]
```

Then re-export each pack and refresh the page.

## Notes

- Serve over HTTP (not `file://`) so ES modules and fetch work.
- Globe uses Three.js from jsDelivr CDN, fetched on first switch to globe mode (needs network once; flat map never downloads it).
- Full-planet packs should use lower `--max-dim` or multi-res later; this viewer loads one mosaic per pack.

## Keyboard / mouse

- **Flat:** drag pan, scroll zoom, hover settlements
- **Globe:** drag orbit, scroll dolly

## Pack selection and hosting

The `pack` query parameter is relative to the viewer root. For example,
`?pack=data/demo` loads `viewer/data/demo/viewer.json`. Keep catalog paths
relative as well so the static site can be hosted below a URL prefix.

The built-in `realearth serve` command is intended for local inspection. It is
threaded (pack artifacts load in parallel), gzips text assets (HTML/CSS/JS/JSON)
when the client accepts them, and sends `Cache-Control: no-cache` so edited packs
revalidate via `If-Modified-Since` 304s. For a shared deployment, any static HTTP
server can host `viewer/` as long as it sends JSON, JavaScript, and PNG files
with normal MIME types and permits the viewer to fetch its data paths. The globe
imports Three.js from a public CDN, so a strict Content Security Policy or
offline deployment must vendor/allow that dependency.

## Troubleshooting

- A blank page opened with `file://` is expected; start the HTTP server instead.
- A missing pack usually means `viewer.json` was not exported at the path named
  by `?pack=` or `catalog.json`.
- If a layer is blank, inspect the browser network panel for missing PNG files
  and re-run `realearth export-viewer` from the matching source pack.
- Very large mosaics consume substantial browser memory. Re-export with a lower
  maximum dimension or split the dataset into catalog entries.
- Cursor elevation is approximate and comes from the exported raw elevation
  image, not a live query against the source DEM.

## Development notes

Sources are TypeScript under `src/`: `app.ts` coordinates controls and
datasets, `pack.ts` parses pack artifacts, `map2d.ts` renders the flat view,
and `globe.ts` renders the sphere (`types.ts`/`coerce.ts` hold the shared data
shapes and JSON boundary coercion). esbuild compiles them to the served ES
modules in `js/`; three.js stays external and is resolved by the importmap at
runtime, so the CDN fetch still happens only when Globe mode is first used.

```bash
# from repo root: rebuild js/ after editing src/, then type-check + lint
make viewer-build
make viewer-lint   # tsc --strict (viewer/tsconfig.json) + oxlint, anti-slop + strict
```

`make serve` rebuilds before serving. After editing, test both views, pack switching, settlement
hover, cursor probing, and a narrow/mobile viewport.
