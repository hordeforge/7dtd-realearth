# Host world (Streamed absolute window)

The engine loads **one finite host** of size `LocalWindowSize` (default **1024**, or pack size for regional demos).

That host is **not** the whole planet and is **not** “always fully meshed.” It is a sliding **coordinate canvas**:

- Absolute / pack position is continuous.
- Host origin slides so you stay near the center (`SoloSlide`).
- `.rte` tiles stream in a small bubble; **all concrete** `GetTerrainHeight*` methods are Harmony-patched (including RWG `TerrainGeneratorWithBiomeResource`, not only the first 4), plus `GenerateTerrain` rewrite of **SetBlock + SetDensity** from `FillChunkHeights`.
- Vanilla view/sim distance decides which game chunks are really hot (often much less than 1024).

## Setup (Streamed)

1. Install: `MAP_MODE=Streamed scripts/install_proton.sh` (default).
2. Mod ships `Data/tiles` (demo region pack or your own). `earth.manifest.json` sets pack world size + bbox.
3. Generate any RWG / empty world of size matching `LocalWindowSize` (or use a small pregen host).
4. New game on that host; RuntimeHooks center on spawn lon/lat, stream tiles, inject terrain per chunk.

## Setup (Baked)

1. `MAP_MODE=Baked scripts/install_proton.sh` installs GeneratedWorlds/RealEarth DTM.
2. New Game → world **RealEarth** (finite heightmap, no .rte inject required).

See [`docs/ABSOLUTE_STREAMING.md`](ABSOLUTE_STREAMING.md). Offline proof: `realearth sample-chunk --pack data/samples/demo_region --lon -104.99 --lat 39.74`.
