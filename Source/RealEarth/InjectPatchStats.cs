namespace RealEarth
{
    /// <summary>
    /// Counts successful Harmony binds for height inject (diagnostics / loadgen gates).
    /// </summary>
    public static class InjectPatchStats
    {
        public static int HeightQueryPatches { get; private set; }
        public static int GenerateTerrainPatches { get; private set; }
        public static int ChunkIndexPatches { get; private set; }
        public static int PlayerTickPatches { get; private set; }
        public static int WorldReadyPatches { get; private set; }

        public static void Reset()
        {
            HeightQueryPatches = 0;
            GenerateTerrainPatches = 0;
            ChunkIndexPatches = 0;
            PlayerTickPatches = 0;
            WorldReadyPatches = 0;
        }

        public static void AddHeightQuery(int n)
        {
            if (n > 0) HeightQueryPatches += n;
        }

        public static void AddGenerateTerrain(int n)
        {
            if (n > 0) GenerateTerrainPatches += n;
        }

        public static void AddChunkIndex(int n)
        {
            if (n > 0) ChunkIndexPatches += n;
        }

        public static void AddPlayerTick(int n)
        {
            if (n > 0) PlayerTickPatches += n;
        }

        public static void AddWorldReady(int n)
        {
            if (n > 0) WorldReadyPatches += n;
        }

        /// <summary>Any height or gen bind (diagnostic / stock-safe).</summary>
        public static bool HasMinimalInjectBinding =>
            HeightQueryPatches > 0 || GenerateTerrainPatches > 0;

        /// <summary>
        /// Product Streamed tall path needs GenerateTerrain rewrite when engine is expanded
        /// (byte height queries alone cannot drive solid Everest columns).
        /// </summary>
        public static bool HasProductInjectBinding
        {
            get
            {
                if (GenerateTerrainPatches > 0)
                    return true;
                // Stock / non-expanded: height queries may be enough for ~250 columns.
                if (!EngineHeight.EngineHeightMod.EngineExpanded && HeightQueryPatches > 0)
                    return true;
                return false;
            }
        }

        public static string FormatSummary() =>
            $"heightQ={HeightQueryPatches} gen={GenerateTerrainPatches} " +
            $"chunkIdx={ChunkIndexPatches} playerTick={PlayerTickPatches} worldReady={WorldReadyPatches} " +
            $"injectOk={HasMinimalInjectBinding} productOk={HasProductInjectBinding} " +
            $"missTiles={TileSamplePolicy.MissingTileHits} presentTiles={TileSamplePolicy.PresentTileHits} " +
            $"sessionInject={ChunkTerrainInject.SessionInjectCount} peakY={ChunkTerrainInject.SessionPeakHeight}";
    }
}
