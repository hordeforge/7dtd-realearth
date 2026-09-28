using System.Threading;

namespace RealEarth
{
    /// <summary>
    /// Counts successful Harmony binds for height inject (diagnostics / loadgen gates).
    ///
    /// Binds are counted from the main thread (RuntimeHooks.Apply / TryRetryApply)
    /// while `reinject`, the inject gate, and FormatSummary read them from the
    /// console/telnet thread. Plain read-modify-write lost updates there and let a
    /// reader mix pre-Reset and post-Reset fields into one verdict, so the counters
    /// are plain fields with Interlocked/Volatile access instead of properties.
    /// </summary>
    public static class InjectPatchStats
    {
        static int _heightQueryPatches;
        static int _generateTerrainPatches;
        static int _chunkIndexPatches;
        static int _playerTickPatches;
        static int _worldReadyPatches;

        public static int HeightQueryPatches => Volatile.Read(ref _heightQueryPatches);
        public static int GenerateTerrainPatches => Volatile.Read(ref _generateTerrainPatches);
        public static int ChunkIndexPatches => Volatile.Read(ref _chunkIndexPatches);
        public static int PlayerTickPatches => Volatile.Read(ref _playerTickPatches);
        public static int WorldReadyPatches => Volatile.Read(ref _worldReadyPatches);

        public static void Reset()
        {
            Interlocked.Exchange(ref _heightQueryPatches, 0);
            Interlocked.Exchange(ref _generateTerrainPatches, 0);
            Interlocked.Exchange(ref _chunkIndexPatches, 0);
            Interlocked.Exchange(ref _playerTickPatches, 0);
            Interlocked.Exchange(ref _worldReadyPatches, 0);
        }

        public static void AddHeightQuery(int n)
        {
            if (n > 0) Interlocked.Add(ref _heightQueryPatches, n);
        }

        public static void AddGenerateTerrain(int n)
        {
            if (n > 0) Interlocked.Add(ref _generateTerrainPatches, n);
        }

        public static void AddChunkIndex(int n)
        {
            if (n > 0) Interlocked.Add(ref _chunkIndexPatches, n);
        }

        public static void AddPlayerTick(int n)
        {
            if (n > 0) Interlocked.Add(ref _playerTickPatches, n);
        }

        public static void AddWorldReady(int n)
        {
            if (n > 0) Interlocked.Add(ref _worldReadyPatches, n);
        }

        /// <summary>
        /// Any height or gen bind (diagnostic / stock-safe). One atomic snapshot of
        /// both fields so a concurrent Reset cannot produce a mixed verdict.
        /// </summary>
        public static bool HasMinimalInjectBinding =>
            (HeightQueryPatches | GenerateTerrainPatches) > 0;

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
            TileLoadStats.FormatSummary() + " " +
            $"sessionInject={ChunkTerrainInject.SessionInjectCount} peakY={ChunkTerrainInject.SessionPeakHeight}";
    }
}
