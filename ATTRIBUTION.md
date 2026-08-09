# Data attribution

RealEarth is a pipeline and game mod. **You** must supply or download geospatial datasets
according to their licenses. Do not redistribute restricted elevation products with the mod.

## Do not use

| Dataset | Why |
|---|---|
| Google Earth / Google Maps bulk tiles, elevation, Street View | ToS forbid mass download and reuse as mapping/game datasets |

See `docs/REALISM_AND_GOOGLE_EARTH.md`.

## Likely sources (when you enable them)

| Dataset | Use | Typical terms |
|---|---|---|
| Open-Meteo Elevation API | Demo region fetches | Check open-meteo.com terms; attribution appreciated |
| Copernicus DEM GLO-30 | Production elevation | Free access with registration/terms; attribution required |
| SRTM | Elevation | Public domain (US Government) |
| AWS Terrain Tiles / Mapzen Terrarium | Web elevation tiles (`--source terrarium`) | AWS Open Data / Terrarium encoding |
| ESA WorldCover | Land cover | CC BY 4.0 (attribution) |
| OpenStreetMap | Roads, water, places | ODbL (share-alike for derived databases) |
| Natural Earth | Countries, populated places | Public domain |
| WorldPop / GHSL | Population grids | Check product license |
| GeoNames | Place names / population | Creative Commons / terms on geonames.org |

## Built-in demo content

- Procedural synthetic elevation (no third-party DEM)
- Approximate seed city coordinates/populations for testing POI density only

## Game

7 Days to Die is © The Fun Pimps. This project is an unofficial fan mod and is not affiliated with TFP.
