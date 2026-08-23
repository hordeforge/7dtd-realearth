# RealEarth web map viewer

Browser UI for tile packs: **flat pan/zoom map** and **3D globe**, with elevation, land cover, population, and settlement layers.

## Quick start

From the repo (with tools installed):

```bash
# from repo root (or tools/)
make setup

# 1) Build a tile pack (if you do not already have one)
make demo
# or: cd tools && uv run realearth demo --out ../data/samples/demo_region

# 2) Export viewer mosaics into viewer/data/demo
cd tools && uv run realearth export-viewer \
  --pack ../data/samples/demo_region \
  --out ../viewer/data/demo

# 3) Serve the static site
uv run realearth serve
# open http://127.0.0.1:8765/
# or from repo root: make serve
```

Optional query: `http://127.0.0.1:8765/?pack=data/demo`

## Features

| Feature | Description |
|---|---|
| Flat map | Pan, zoom, opacity, tile grid overlay |
| Globe | Three.js sphere; region packs drawn on Earth with bbox highlight |
| Layers | Hybrid, elevation (hillshade), land cover, population density |
| Settlements | Markers + hover tooltip from `settlements.json` |
| Probe | Lon/lat under cursor; approximate elevation from raw elev PNG |
| Multi-pack | `data/catalog.json` lists extra datasets |

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

`js/app.js` coordinates controls and datasets, `js/map2d.js` renders the flat
view, and `js/globe.js` renders the sphere. After editing, test both views, pack switching, settlement
hover, cursor probing, and a narrow/mobile viewport.
