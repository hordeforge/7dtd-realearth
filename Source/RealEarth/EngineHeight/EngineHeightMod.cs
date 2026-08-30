using System;

namespace RealEarth.EngineHeight
{
    /// <summary>
    /// Height module for RealEarth (YDim expand is part of this mod).
    /// <list type="bullet">
    /// <item><b>Product:</b> real elevation, 1 m = 1 block after YDim expand (Tools/apply_engine_expand or make engine-expand).</item>
    /// <item><b>Opt-in only:</b> EngineHeightStockSafe compresses into ~0–250 on stock engines. Not the product path.</item>
    /// </list>
    /// </summary>
    public static class EngineHeightMod
    {
        public static WorldConstantsProbe? Probe { get; private set; }
        public static EngineHeightPolicy? Policy { get; private set; }
        public static AbsoluteHeightStore Store { get; } = new AbsoluteHeightStore(16);
        public static bool Active => Policy != null && Policy.Enabled;
        /// <summary>
        /// True when product real-height requires YDim expand but the engine is still stock
        /// and StockSafe is off. Heights still inject but clamp to AllocatableColumnMaxY;
        /// never claim Everest-scale columns without expand.
        /// </summary>
        public static bool ProductHeightBlocked { get; private set; }

        public static void Init(RealEarthConfig cfg)
        {
            Probe = WorldConstantsProbe.Probe();
            ProductHeightBlocked = false;

            // Cap configured MaxGameY
            if (cfg.EngineMaxGameY <= 0)
                cfg.EngineMaxGameY = HeightCompress.EngineTargetMaxY;
            if (cfg.EngineMaxGameY > HeightCompress.EngineTargetMaxY)
                cfg.EngineMaxGameY = HeightCompress.EngineTargetMaxY;

            // Product path: always prefer 1:1. StockSafe is an explicit opt-in compress mode.
            if (Probe.ChunkBlockYDim <= 256 && cfg.EngineHeightStockSafe)
            {
                cfg.EngineHeightPreferVanillaCeiling = true;
                cfg.EngineHeightOneToOne = false;
            }
            else
            {
                cfg.EngineHeightPreferVanillaCeiling = false;
                cfg.EngineHeightOneToOne = true;
            }

            Policy = new EngineHeightPolicy(Probe, cfg);
            Store.Clear();
            ModApi.Log($"EngineHeightMod: {Policy.Describe()}");

            if (!cfg.EnableEngineHeightMod)
                return;

            if (EngineExpanded)
            {
                // Effective YDim: the hot patch rewrites literals at JIT, so the
                // probe still reads 256 on a stock engine while it runs 32768.
                int effectiveYDim = RuntimeYDimTranspiler.IsActive
                    ? RuntimeYDimTranspiler.TargetYDim
                    : Probe?.ChunkBlockYDim ?? 256;
                ModApi.Log(
                    $"EngineHeightMod: RealEarth YDim expand active YDim={effectiveYDim} " +
                    $"({(RuntimeYDimTranspiler.IsActive ? "runtime hot patch" : "disk patch")}) - " +
                    $"real height 1:1 up to content maxY={Policy.MaxGameY}. " +
                    "Restore stock: make engine-restore (or Steam Verify).");
            }
            else if (cfg.EngineHeightStockSafe)
            {
                ModApi.LogWarn(
                    $"EngineHeightMod: OPT-IN compress on stock YDim={Probe?.ChunkBlockYDim ?? 256} " +
                    "(~0-250). Product path is real height: make engine-expand, set " +
                    "EngineHeightStockSafe=false, restart.");
            }
            else
            {
                // Hard gate: refuse product tall inject when expand is required but missing.
                ProductHeightBlocked = ExpandProductGuard.RequiresExpandForRealHeight(
                    cfg.EngineHeightStockSafe,
                    cfg.EngineHeightOneToOne,
                    Probe?.ChunkBlockYDim ?? 256);
                ModApi.LogWarn(
                    $"EngineHeightMod: stock YDim={Probe?.ChunkBlockYDim ?? 256}, real-height mode - " +
                    "apply RealEarth YDim expand (Tools/apply_engine_expand.sh or make engine-expand) " +
                    "before playable tall columns. " +
                    (ProductHeightBlocked
                        ? $"HEIGHT CAPPED to allocY={AllocatableColumnMaxY} until expand " +
                          "(inject still runs clamped; not Everest-scale). Or set EngineHeightStockSafe=true."
                        : "Compression is not the product path."));
            }
        }

        public static bool EngineExpanded =>
            Probe != null
            && ExpandProductGuard.IsExpanded(Probe.ChunkBlockYDim, RuntimeYDimTranspiler.IsActive);

        public static int AllocatableColumnMaxY
        {
            get
            {
                int content = Policy?.MaxGameY ?? 250;
                // Runtime hot-patch: the const still reads 256, but JIT'd methods
                // allocate TargetYDim columns; use the target so the inject and
                // AllocatableColumnMaxY agree with the engine's actual capacity.
                int engine = RuntimeYDimTranspiler.IsActive
                    ? RuntimeYDimTranspiler.TargetYDim
                    : Probe?.ChunkBlockYDim > 0 ? Probe.ChunkBlockYDim : 256;
                int cap = Math.Max(2, engine - 1);
                return Math.Min(content, cap);
            }
        }

        public static int SampleGameHeightInt(int localX, int localZ)
        {
            var session = ModApi.Session;
            var streamer = ModApi.Streamer;
            var policy = Policy;
            var cfg = ModApi.Config;
            int sea = policy?.SeaLevelGameY
                      ?? cfg?.SeaLevelGameY
                      ?? HeightInjectMath.DefaultSeaLevelGameY;
            int maxY = policy?.MaxGameY
                       ?? (cfg != null && cfg.EngineMaxGameY > 0
                           ? cfg.EngineMaxGameY
                           : HeightCompress.EngineTargetMaxY);

            // One mapping decision: policy owns the mode; 1:1 fallback keeps
            // unpoliced contexts (policy null) on the linear product path.
            int MapElev(float elevM) => policy != null
                ? policy.MapMetersToGameY(elevM)
                : HeightInjectMath.MetersToGameYOneToOne(elevM, sea, maxY);

            if (session != null && streamer != null)
            {
                session.LocalToEarth(localX, localZ, out int ex, out int ez);
                // Single-lock sample: hot tile inline, miss queues async prefetch.
                // Never registers focusId=0 from the height sample path.
                bool ok = streamer.TrySamplePrefetch(ex, ez, out float elevM, out _, out _);
                // Product path: fail-closed missing tiles + counters (same as ChunkTerrainSampler).
                bool present = TileSamplePolicy.ResolveElev(
                    ok, elevM, cfg, out float elevResolved, out _);
                if (present)
                    Store.SetSurfaceMetersEarth(ex, ez, elevResolved);
                // Map elev (real DEM or fail-closed ocean placeholder) through height policy.
                return ClampToAllocatable(MapElev(elevResolved));
            }

            if (Store.TryGetSurfaceMeters(localX, localZ, out float cached))
            {
                // Cached values were written only on present DEM samples.
                return ClampToAllocatable(MapElev(cached));
            }

            // No session/streamer: still fail-closed ocean (count as miss).
            TileSamplePolicy.ResolveElev(false, 0f, cfg, out float elevMiss, out _);
            return ClampToAllocatable(MapElev(elevMiss));
        }

        static int ClampToAllocatable(int gameY)
        {
            int cap = AllocatableColumnMaxY;
            if (gameY < 1) return 1;
            if (gameY > cap) return cap;
            return gameY;
        }

        public static byte SampleGameHeight(int localX, int localZ)
        {
            return HeightInjectMath.ToByteHeight(SampleGameHeightInt(localX, localZ));
        }
    }
}
