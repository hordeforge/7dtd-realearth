# Realism data: Google Earth vs what we can use

**Owns:** legal/policy “what we may use.” Download lists: [DATA_SOURCES](DATA_SOURCES.md). Hub: [INDEX](INDEX.md).

## Short answer

**No, we cannot re-use Google Earth / Google Maps bulk data** (satellite imagery, 3D buildings, elevation API dumps, Street View, etc.) inside RealEarth for distribution or baking game worlds.

That does **not** mean the mod has to look fake. The same kinds of layers Google shows (height, land cover, cities, roads, population) exist as **open scientific / community datasets** that are legal to download, process, and ship (with attribution).

## Why not Google Earth / Maps

Google’s geo terms (Maps / Earth / Maps Platform) prohibit, among other things:

- Mass download / bulk feeds of content  
- Scraping elevation, tiles, Places, Street View for use outside Google’s services  
- Building or augmenting a mapping dataset that substitutes for Google Maps  
- Using Google Earth imagery in commercial / promotional apps (and bulk use generally)

Even paid Maps Platform has **no-scrape / no bulk store / no terrain-model-from-Elevation-API** style restrictions.

**Bottom line for RealEarth:** do not scrape Google Earth, do not bulk-download Google tiles, do not bake Google elevation into `.rte` / `dtm.raw`.

## What Google *looks like* vs open replacements

| Google-ish layer | Open replacement | Typical license | RealEarth use |
|---|---|---|---|
| Terrain / 3D ground | **Copernicus DEM GLO-30** (~30 m) | Copernicus free (with terms) | Height / `dtm.raw` |
| Terrain (web tiles) | **AWS Terrain Tiles (Terrarium)** | Open (dataset terms) | Pipeline `source=terrarium` |
| Terrain (US / many areas) | **SRTM**, 3DEP (USGS) | Public domain / open | GeoTIFF ingest |
| Satellite color | **Sentinel-2**, Landsat | Free with attribution | Optional future texture; not required for voxels |
| Land use / biomes | **ESA WorldCover** 10 m | CC BY 4.0 | Biome paint |
| Cities / places | **Natural Earth**, **GeoNames** | PD / CC | Named cores, POI plan |
| Population density | **WorldPop**, **GHSL-POP** | Open + credit | Density field, metro bands |
| Building fabric | **GHS-BUILT** | Open + credit | Built-up boost for stamps |
| Building footprints (optional) | **OSM buildings** | ODbL | Future vector stamps |
| Roads / rivers | **OpenStreetMap** | ODbL | Road stamps, rivers (future) |
| Coastlines / lakes | **GSHHG**, OSM water, HydroSHEDS | Open | Water mask |

These are what professional “realistic Earth in a game” pipelines use (Minecraft Earth-style tools, flight sims, strategy games). They are often **better documented and more consistent** for offline bake than scraping Google.

## Realism in 7DTD still has hard limits

Even with perfect DEM:

| Limit | Effect |
|---|---|
| Max ~16k world edge | One baked map is only ~16 km at 1 m/block |
| Height | Product: real meters after YDim expand (not compress-into-255) |
| Voxel POIs | Not real buildings; density stamps from population |
| No Google photogrammetry | No true 3D cities from Earth |

For “feels like real Earth” prioritize:

1. Real DEM (Copernicus / Terrarium / SRTM)  
2. Correct coastlines & rivers  
3. Population-driven city density  
4. Climate-aware biomes (WorldCover + latitude)  
5. Optional Streamed mode for larger travel later  

## Recommended realism stack (legal)

1. **Elevation:** Copernicus GLO-30 via OpenTopography / ESA, or Terrarium tiles for quick regions  
2. **Land cover:** ESA WorldCover  
3. **Settlements:** Natural Earth + GeoNames  
4. **Population:** WorldPop or GHSL  
5. **Roads/water:** OSM Geofabrik extract for your country  

Always ship attribution in `ATTRIBUTION.md` / tile-pack notes.

## Pipeline sources (tools)

```bash
# Synthetic (offline demo)
realearth build-region ... --source synthetic

# Real elevation API samples (small boxes, rate-limited)
realearth build-region ... --source open_meteo

# Real DEM via open Terrarium tiles (good regional realism, no Google)
realearth build-region ... --source terrarium --resolution 30

# Local GeoTIFF (best quality: download Copernicus/SRTM yourself)
realearth build-region ... --source geotiff --geotiff /path/to/dem.tif
```

Then:

```bash
realearth bake-world --pack ... --out worlds/RealEarth --generated
./scripts/install_proton.sh
```

## Google Earth Engine?

Earth Engine is a **compute platform**. Some **underlying** datasets are open (e.g. Copernicus DEM catalog entries). You may process open layers there for research, then export **those open products**. You still cannot treat Engine as a free Google Earth dump for commercial game redistribution without following each dataset’s license and Google’s Engine terms.

## Practical “max realism” plan for this mod

| Phase | Action |
|---|---|
| Now | `terrarium` or `open_meteo` for real heights; seed cities; heuristic biomes |
| Next | GeoTIFF ingest of Copernicus GLO-30 for your home region at 30 m |
| Next | WorldCover raster → exact forest/desert/snow/urban |
| Later | OSM roads + waterways as stamps |
| Later | Population grid → metro density |

## Attribution stubs

When using open data, keep something like:

```
Elevation: Copernicus DEM GLO-30 / AWS Terrain Tiles (Terrarium)
Land cover: ESA WorldCover
Places: Natural Earth / GeoNames
Roads: © OpenStreetMap contributors (ODbL)
```

## References

- [Google Maps End User Additional Terms](https://www.google.com/help/terms_maps/)  
- [Google geo permissions / Earth guidelines](https://about.google/brand-resource-center/products-and-services/geo-guidelines/)  
- [Maps Platform: no scraping / no bulk elevation models](https://cloud.google.com/maps-platform/terms)  
- [OpenTopography Copernicus GLO-30](https://portal.opentopography.org/raster?opentopoID=OTSDEM.032021.4326.3)  
- [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/)

## Related docs

| Doc | Role |
|---|---|
| [DATA_SOURCES](DATA_SOURCES.md) | Download products |
| [CITIES_AND_DENSITY](CITIES_AND_DENSITY.md) | Density pipeline |
| [ATTRIBUTION](../ATTRIBUTION.md) | Licenses |

## Changelog

- **2026-07-19:** Ownership header; related docs.
