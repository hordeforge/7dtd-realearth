# Tile farm, cache, CDN, update, and storage plan

**Owns:** the practical plan for producing, storing, distributing, and updating
RealEarth tile packs from a single region up to a full planet. Data sources and
licenses: [DATA_SOURCES.md](DATA_SOURCES.md) / [ATTRIBUTION.md](../ATTRIBUTION.md).
Hub: [INDEX.md](INDEX.md).

## 1. Terminology

| Term | Meaning |
|---|---|
| `.rte` tile | 512x512 (default) elevation+landcover+population tile; signed meters ASL |
| pack | a `tiles/` tree + `earth.manifest.json` + `build.json` + optional settlements |
| build manifest | `build.json` (schema `realearth.build.v1`): bbox, resolution, source, input sha256, params, attribution |
| cache | local disk cache of fetched DEM tiles (Terrarium PNGs etc.) |
| CDN | optional HTTP base for tiles the streamer can fetch when a pack tile is absent (`TileCdnBaseUrl`) |

## 2. Build cache (producer side)

The offline pipeline caches raw DEM tiles under a disk-backed directory so
re-building a region does not re-download:

```bash
realearth build-region --west ... --source terrarium --terrarium-zoom 11 \
  --out data/samples/region_a
```

`fetch_region_terrarium` reads/writes `terrarium_cache_dir()` (project disk
cache, not tmpfs): `{zoom}/{tx}/{ty}.png`, keyed by zoom + tile indices. Rules:

- Only validated tiles enter the cache (a corrupt-but-200 body must not shadow
  the source until a refetch overwrites it).
- Cache is content-addressed by source tile coordinate; rebuilding at a higher
  zoom adds entries without invalidating lower zooms.
- Back up with `make artifacts-backup` (see [BACKUP_RESTORE.md](BACKUP_RESTORE.md)).

## 3. Build manifests for reproducibility

Every `build-region` run writes `build.json` next to `earth.manifest.json`:

```json
{
  "schema": "realearth.build.v1",
  "tool_version": "0.3.0",
  "bbox": {...},
  "resolution_m": 30.0,
  "samples": {"width": ..., "height": ...},
  "source": "terrarium",
  "inputs": {"geotiff": {"file": "copernicus.tif", "sha256": "..."}},
  "attribution": [...]
}
```

Verify a pack's inputs still match their hashes:

```bash
realearth verify-build --pack data/samples/region_a
```

A pack is re-derivable when its build.json + input files (hashes checked) +
tool version are known. Publish the manifest alongside the pack so consumers
can audit provenance before trusting the data.

## 4. Storage layout

Recommended layout for a region or planet farm (mirrors the streamer's
`TileFilePath`):

```text
tiles/{tz}/{tx}.rte          # elevation/landcover/population tiles
earth.manifest.json          # bbox, tile grid, sources
build.json                   # reproducibility record (schema v1)
settlements.json             # optional city catalog
```

Sizing guidance:

| Scope | Tiles (512 px) | Uncompressed-ish on disk |
|---|---|---|
| Demo region (~0.3 deg) | 4 | ~1 MB |
| Country (~10 deg) | ~500 | ~100 MB |
| Full Earth at 1:1 | 60k x 30k grid | TB-class (do not materialize as one pack) |

Full-planet strategy: regional packs + progressive resolution, never one giant
mosaic. The viewer's in-browser `.rte` streaming (relief layer) exists for
packs too large for a single mosaic.

## 5. Distribution (CDN)

- `TileCdnBaseUrl` lets the runtime fetch a missing tile from an HTTP base
  instead of failing the chunk; the path appended is `tiles/{tz}/{tx}.rte`
  (same layout as packs).
- Signed manifests: publish `build.json` + `earth.manifest.json` at the CDN
  root; clients that verify `verify-build` before consuming get provenance.
- Fail-closed: a missing/corrupt tile renders ocean floor, never a fake DEM
  peak (`failClosed=True`; see [MODIFICATIONS.md](MODIFICATIONS.md)).
- Updates: packs are content-addressed by manifest; a new build increments
  `build.json` (schema version + tool version + input hashes), so a CDN cache
  can key on the manifest hash.

## 6. Cache / update discipline

- Producers: disk-backed DEM cache (section 2) + `make artifacts-backup`.
- Consumers: the mod streams a local bubble; `UnloadRadiusTiles` bounds
  resident chunks. `TileCdnBaseUrl` is the only network dependency at runtime
  and it is optional.
- After a data update, re-export packs (`make package` regenerates
  `dist/realearth-deps.spdx.json`); `make artifacts-restore` rolls back.

## 7. Open work

- Road/river corridors from OSM (ODbL) as a later stamp layer.
- Automatic regional manifest publishing to the CDN (currently manual upload
  of the pack directory).
- Progressive resolution (coarse tiles for far chunks, fine tiles near the
  player) - DESIGN P4 / later.

## Related docs

| Doc | Role |
|---|---|
| [DATA_SOURCES.md](DATA_SOURCES.md) | Where elevation/landcover/pop come from |
| [ATTRIBUTION.md](../ATTRIBUTION.md) | License obligations per dataset |
| [BACKUP_RESTORE.md](BACKUP_RESTORE.md) | Artifact backup/restore, RPO/RTO |
| [DESIGN.md](../DESIGN.md) | Architecture; P4 planet farm |
