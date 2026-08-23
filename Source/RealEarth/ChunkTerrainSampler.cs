using System;

namespace RealEarth
{
    /// <summary>
    /// Samples continuous RealEarth terrain for any local chunk cell.
    /// Streamed mode: local engine XZ → absolute Earth → .rte sample → game Y / landcover.
    /// Pure overloads take explicit session/streamer so inject logic is testable without the game loop.
    /// </summary>
    public static class ChunkTerrainSampler
    {
        public const int VanillaChunkSize = 16;

        public static byte SampleGameHeight(int localX, int localZ)
        {
            return SampleGameHeight(ModApi.Session, ModApi.Streamer, ModApi.Config, localX, localZ);
        }

        /// <summary>Full int height (up to EngineMaxGameY / 11000 when engine-height mod is on).</summary>
        public static int SampleGameHeightInt(int localX, int localZ)
        {
            if (EngineHeight.EngineHeightMod.Active)
                return EngineHeight.EngineHeightMod.SampleGameHeightInt(localX, localZ);
            // Never route int API through byte SampleGameHeight (would clamp tall Y to 255).
            return SampleGameHeightIntExplicit(
                ModApi.Session, ModApi.Streamer, ModApi.Config, localX, localZ);
        }

        public static byte SampleLandcover(int localX, int localZ)
        {
            return SampleLandcover(ModApi.Session, ModApi.Streamer, localX, localZ);
        }

        public static byte SamplePopulation(int localX, int localZ)
        {
            return SamplePopulation(ModApi.Session, ModApi.Streamer, localX, localZ);
        }

        /// <summary>
        /// Sample game surface height at engine-local block coords using explicit deps.
        /// Missing tile → ocean default (below sea level).
        /// </summary>
        public static byte SampleGameHeight(
            WorldSession? session,
            TileStreamer? streamer,
            RealEarthConfig? cfg,
            int localX,
            int localZ)
        {
            // Engine-height path: sparse absolute meters + policy (up to 11000, byte-scaled for stock APIs)
            if (EngineHeight.EngineHeightMod.Active)
                return EngineHeight.EngineHeightMod.SampleGameHeight(localX, localZ);

            int sea = cfg?.SeaLevelGameY ?? HeightInjectMath.DefaultSeaLevelGameY;
            if (session == null || streamer == null)
                return HeightInjectMath.ToByteHeight(sea);

            session.LocalToEarth(localX, localZ, out int ex, out int ez);
            // Single-lock sample: hot tile inline, miss queues async prefetch (no focus).
            bool ok = streamer.TrySamplePrefetch(ex, ez, out float elevM, out _, out _);
            TileSamplePolicy.ResolveElev(ok, elevM, cfg, out float elevResolved, out _);
            int h = TileSamplePolicy.ElevToGameYInt(elevResolved, cfg);
            return HeightInjectMath.ToByteHeight(h);
        }

        /// <summary>
        /// Fill int heights for a chunk (supports 11000). heights[z * chunkSize + x] = game Y.
        /// </summary>
        public static void FillChunkHeightsInt(
            WorldSession? session,
            TileStreamer? streamer,
            RealEarthConfig? cfg,
            int chunkLocalOriginX,
            int chunkLocalOriginZ,
            int chunkSize,
            int[] heights)
        {
            if (heights == null || heights.Length < chunkSize * chunkSize)
                throw new ArgumentException("heights buffer too small");

            for (int z = 0; z < chunkSize; z++)
            {
                for (int x = 0; x < chunkSize; x++)
                {
                    int lx = chunkLocalOriginX + x;
                    int lz = chunkLocalOriginZ + z;
                    if (EngineHeight.EngineHeightMod.Active)
                        heights[z * chunkSize + x] = EngineHeight.EngineHeightMod.SampleGameHeightInt(lx, lz);
                    else
                        heights[z * chunkSize + x] = SampleGameHeightIntExplicit(session, streamer, cfg, lx, lz);
                }
            }
        }

        /// <summary>Int height with fail-closed missing tiles (no EngineHeightMod path).</summary>
        public static int SampleGameHeightIntExplicit(
            WorldSession? session,
            TileStreamer? streamer,
            RealEarthConfig? cfg,
            int localX,
            int localZ)
        {
            int sea = cfg?.SeaLevelGameY ?? HeightInjectMath.DefaultSeaLevelGameY;
            if (session == null || streamer == null)
                return sea;

            session.LocalToEarth(localX, localZ, out int ex, out int ez);
            bool ok = streamer.TrySamplePrefetch(ex, ez, out float elevM, out _, out _);
            TileSamplePolicy.ResolveElev(ok, elevM, cfg, out float elevResolved, out _);
            int y = TileSamplePolicy.ElevToGameYInt(elevResolved, cfg);
            int cap = EngineHeight.EngineHeightMod.AllocatableColumnMaxY;
            if (y > cap) y = cap;
            if (y < 1) y = 1;
            return y;
        }

        public static byte SampleLandcover(
            WorldSession? session,
            TileStreamer? streamer,
            int localX,
            int localZ)
        {
            if (session == null || streamer == null)
                return 255;

            session.LocalToEarth(localX, localZ, out int ex, out int ez);
            // Landcover used during inject after height fill; hot tiles only (async prefetch on miss).
            // Callers that need a guaranteed sample should EnsureHotAround(..., allowSyncLoad: true) first.
            if (streamer.TrySamplePrefetch(ex, ez, out _, out byte lc, out _))
                return lc;
            return 0; // ocean / miss
        }

        public static byte SamplePopulation(
            WorldSession? session,
            TileStreamer? streamer,
            int localX,
            int localZ)
        {
            if (session == null || streamer == null)
                return 0;

            session.LocalToEarth(localX, localZ, out int ex, out int ez);
            if (streamer.TrySamplePrefetch(ex, ez, out _, out _, out byte pop))
                return pop;
            return 0;
        }

        /// <summary>
        /// Sample using absolute Earth blocks (no local-window mapping).
        /// Used when hooks pass world XZ that already match host absolute mapping.
        /// </summary>
        public static byte SampleGameHeightAbsolute(
            TileStreamer? streamer,
            RealEarthConfig? cfg,
            int earthX,
            int earthZ)
        {
            int sea = cfg?.SeaLevelGameY ?? HeightInjectMath.DefaultSeaLevelGameY;
            if (streamer == null)
                return HeightInjectMath.ToByteHeight(sea);

            bool ok = streamer.TrySamplePrefetch(earthX, earthZ, out float elevM, out _, out _);
            TileSamplePolicy.ResolveElev(ok, elevM, cfg, out float elevResolved, out _);
            int h = TileSamplePolicy.ElevToGameYInt(elevResolved, cfg);
            return HeightInjectMath.ToByteHeight(h);
        }

        public static byte SampleLandcoverAbsolute(TileStreamer? streamer, int earthX, int earthZ)
        {
            if (streamer == null)
                return 255;
            if (streamer.TrySamplePrefetch(earthX, earthZ, out _, out byte lc, out _))
                return lc;
            return 0;
        }

        /// <summary>
        /// Fill a square height buffer for a chunk (chunkSize typically 16).
        /// heights[z * chunkSize + x] = game Y surface.
        /// </summary>
        public static void FillChunkHeights(int chunkLocalOriginX, int chunkLocalOriginZ, int chunkSize, byte[] heights)
        {
            FillChunkHeights(
                ModApi.Session, ModApi.Streamer, ModApi.Config,
                chunkLocalOriginX, chunkLocalOriginZ, chunkSize, heights);
        }

        public static void FillChunkHeights(
            WorldSession? session,
            TileStreamer? streamer,
            RealEarthConfig? cfg,
            int chunkLocalOriginX,
            int chunkLocalOriginZ,
            int chunkSize,
            byte[] heights)
        {
            if (heights == null || heights.Length < chunkSize * chunkSize)
                throw new ArgumentException("heights buffer too small");

            for (int z = 0; z < chunkSize; z++)
            {
                for (int x = 0; x < chunkSize; x++)
                {
                    heights[z * chunkSize + x] = SampleGameHeight(
                        session, streamer, cfg,
                        chunkLocalOriginX + x, chunkLocalOriginZ + z);
                }
            }
        }

        /// <summary>Fill landcover ids for a chunk (same layout as heights).</summary>
        public static void FillChunkLandcover(
            WorldSession? session,
            TileStreamer? streamer,
            int chunkLocalOriginX,
            int chunkLocalOriginZ,
            int chunkSize,
            byte[] landcover)
        {
            if (landcover == null || landcover.Length < chunkSize * chunkSize)
                throw new ArgumentException("landcover buffer too small");

            for (int z = 0; z < chunkSize; z++)
            {
                for (int x = 0; x < chunkSize; x++)
                {
                    landcover[z * chunkSize + x] = SampleLandcover(
                        session, streamer, chunkLocalOriginX + x, chunkLocalOriginZ + z);
                }
            }
        }

        /// <summary>
        /// Heights + landcover for one chunk in the shared layout
        /// (buf[z * chunkSize + x]). One entry point so gen-time inject and
        /// post-slide reinject cannot drift apart.
        /// </summary>
        public static void FillChunkColumns(
            WorldSession? session,
            TileStreamer? streamer,
            RealEarthConfig? cfg,
            int chunkLocalOriginX,
            int chunkLocalOriginZ,
            int chunkSize,
            int[] heights,
            byte[] landcover)
        {
            FillChunkHeightsInt(
                session, streamer, cfg, chunkLocalOriginX, chunkLocalOriginZ, chunkSize, heights);
            FillChunkLandcover(
                session, streamer, chunkLocalOriginX, chunkLocalOriginZ, chunkSize, landcover);
        }

        /// <summary>
        /// Absolute-Earth chunk fill: origin is earth block of chunk corner (not engine-local).
        /// </summary>
        public static void FillChunkHeightsAbsolute(
            TileStreamer? streamer,
            RealEarthConfig? cfg,
            int chunkEarthOriginX,
            int chunkEarthOriginZ,
            int chunkSize,
            byte[] heights)
        {
            if (heights == null || heights.Length < chunkSize * chunkSize)
                throw new ArgumentException("heights buffer too small");

            for (int z = 0; z < chunkSize; z++)
            {
                for (int x = 0; x < chunkSize; x++)
                {
                    heights[z * chunkSize + x] = SampleGameHeightAbsolute(
                        streamer, cfg,
                        chunkEarthOriginX + x, chunkEarthOriginZ + z);
                }
            }
        }

        /// <summary>Map internal landcover code to a coarse biome id string for logging / XML bridge.</summary>
        public static string LandcoverToBiomeName(byte lc)
        {
            switch (lc)
            {
                case 0:
                case 1: return "water";
                case 2:
                case 10: return "snow";
                case 3: return "wasteland";
                case 5:
                case 11: return "desert";
                case 9: return "pine_forest"; // urban underlay
                default: return "pine_forest";
            }
        }
    }
}
