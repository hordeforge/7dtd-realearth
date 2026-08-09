using System;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// Inject RealEarth 1:1 heights into the live engine (no compression).
    /// With engine-expand (YDim=16384), columns are filled solid up to true gameY
    /// (e.g. Everest ≈ 8949). Stock 250 is ignored when the engine is expanded.
    /// </summary>
    public static class ChunkTerrainInject
    {
        static int _injectLogBudget = 24;
        static object? _airBlock;
        static object? _solidBlock;
        static object? _dirtBlock;
        static object? _snowBlock;
        static object? _sandBlock;
        static bool _blocksResolved;
        static MethodInfo? _setHeight;
        static MethodInfo? _setDensityCached;
        static MethodInfo? _setBlockCached;
        static Type? _cachedChunkType;
        /// <summary>Highest maxH seen this session (for dedicated gates / diagnostics).</summary>
        public static int SessionPeakHeight { get; private set; }
        public static int SessionInjectCount { get; private set; }
        public static int SessionBlocksApplied { get; private set; }

        /// <summary>Reset per-world inject counters (WorldReady / reinject reset).</summary>
        public static void ResetSessionCounters()
        {
            SessionPeakHeight = 0;
            SessionInjectCount = 0;
            SessionBlocksApplied = 0;
            _injectLogBudget = 24;
        }

        /// <summary>
        /// When true, product real-height inject is refused (needs expand or patches missing).
        /// </summary>
        public static bool InjectBlocked { get; set; }

        static bool HeightModWantsInject()
        {
            if (InjectBlocked) return false;
            if (ModApi.Session == null) return false;
            // ProductHeightBlocked still injects (clamped to stock YDim); expand banner is separate.
            if (EngineHeight.EngineHeightMod.Active) return true;
            return ModApi.Session.IsStreamed;
        }

        /// <summary>Full int height for float/int terrain APIs (1:1, no compression).</summary>
        public static bool TryOverrideHeightInt(int worldX, int worldZ, out int height)
        {
            height = 0;
            if (!HeightModWantsInject()) return false;
            if (EngineHeight.EngineHeightMod.Active)
                height = EngineHeight.EngineHeightMod.SampleGameHeightInt(worldX, worldZ);
            else
                height = ChunkTerrainSampler.SampleGameHeightIntExplicit(
                    ModApi.Session, ModApi.Streamer, ModApi.Config, worldX, worldZ);
            return true;
        }

        public static bool TryOverrideHeightFloat(int worldX, int worldZ, out float height)
        {
            if (!TryOverrideHeightInt(worldX, worldZ, out int h))
            {
                height = 0f;
                return false;
            }
            height = h;
            return true;
        }

        /// <summary>
        /// Byte API: only used by legacy signatures. When engine is expanded we still
        /// cannot fit 8949 in a byte — inject owns the real column. Return min(255,h).
        /// </summary>
        public static bool TryOverrideHeightByte(int worldX, int worldZ, out byte height)
        {
            height = 0;
            if (!TryOverrideHeightInt(worldX, worldZ, out int h))
                return false;
            height = HeightInjectMath.ToByteHeight(h);
            return true;
        }

        public static void OnChunkGenerated(object? chunkProvider, int chunkX, int chunkZ, object? chunkObj)
        {
            if (!HeightModWantsInject()) return;
            var session = ModApi.Session;
            var streamer = ModApi.Streamer;
            if (session == null || streamer == null) return;

            int blockX = chunkX * ChunkTerrainSampler.VanillaChunkSize;
            int blockZ = chunkZ * ChunkTerrainSampler.VanillaChunkSize;
            session.LocalToEarth(blockX, blockZ, out int ex, out int ez);
            // Gen rewrite must sync-load tiles (async race → permanent ocean columns).
            // Do not register focusId=0 (would stomp MP bubbles).
            streamer.EnsureHotAround(ex, ez, radius: 1, allowSyncLoad: true);

            int n = ChunkTerrainSampler.VanillaChunkSize * ChunkTerrainSampler.VanillaChunkSize;
            var heights = new int[n];
            ChunkTerrainSampler.FillChunkHeightsInt(
                session, streamer, ModApi.Config, blockX, blockZ,
                ChunkTerrainSampler.VanillaChunkSize, heights);

            var landcover = new byte[n];
            ChunkTerrainSampler.FillChunkLandcover(
                session, streamer, blockX, blockZ, ChunkTerrainSampler.VanillaChunkSize, landcover);

            bool applied = false;
            if (chunkObj != null)
                applied = TryApplyHeightsToChunk(chunkObj, heights, landcover);

            // Runtime density/POI stamps for urban cells (budgeted).
            try
            {
                RuntimePoiInject.OnChunkGenerated(chunkX, chunkZ);
            }
            catch { /* never break inject */ }

            // Only count successful column rewrites (null chunk / apply miss do not inflate gates).
            if (applied)
            {
                SessionInjectCount++;
                SessionBlocksApplied++;
                int maxH = 0;
                for (int i = 0; i < heights.Length; i++)
                    if (heights[i] > maxH) maxH = heights[i];
                if (maxH > SessionPeakHeight)
                    SessionPeakHeight = maxH;
            }
            int mid = heights[heights.Length / 2];
            int maxHLog = 0;
            for (int i = 0; i < heights.Length; i++)
                if (heights[i] > maxHLog) maxHLog = heights[i];

            if (_injectLogBudget > 0)
            {
                _injectLogBudget--;
                byte lc = landcover[landcover.Length / 2];
                ModApi.Log(
                    $"Height inject chunk=({chunkX},{chunkZ}) earth=({ex},{ez}) " +
                    $"midH={mid} maxH={maxHLog} sessionPeak={SessionPeakHeight} " +
                    $"allocY={EngineHeight.EngineHeightMod.AllocatableColumnMaxY} " +
                    $"expanded={EngineHeight.EngineHeightMod.EngineExpanded} " +
                    $"biome={ChunkTerrainSampler.LandcoverToBiomeName(lc)} " +
                    $"hotTiles={streamer.HotTileCount} blocks={applied}");
            }
        }

        /// <summary>Default dual-fill ceiling when config auto (stock / safety).</summary>
        public const int DefaultFullDualFillMaxSurface = 520;

        /// <summary>Solid thickness at the top when dual fill is capped (plus thin bedrock plug).</summary>
        const int TallCrustDepth = 48;

        /// <summary>
        /// Effective max surface for full solid block+density fill via reflection.
        /// Never auto-selects Everest-scale dual fill (millions of Invoke calls hang gen).
        /// Config FullSolidBlockFillMaxSurface &gt; 0 opts into a higher dual-fill ceiling.
        /// Tall columns above this: solid density full height + block crust (Issue 2).
        /// </summary>
        public static int EffectiveFullDualFillMaxSurface()
        {
            var cfg = ModApi.Config;
            if (cfg != null && cfg.FullSolidBlockFillMaxSurface > 0)
            {
                // Hard ceiling: never allow multi-million Invoke/chunk hang even if config says 11000.
                const int hardMax = 2048;
                int want = cfg.FullSolidBlockFillMaxSurface;
                if (want > hardMax) want = hardMax;
                return want;
            }
            // Expanded or stock: default dual-fill cap (reflection-safe). Full solid density still covers tall.
            return DefaultFullDualFillMaxSurface;
        }

        /// <summary>
        /// Fill solid terrain for 1:1 heights.
        /// Full dual block+density through EffectiveFullDualFillMaxSurface (default 520).
        /// Above that: solid density entire column + block crust + bedrock (not hollow).
        /// </summary>
        public static bool TryApplyHeightsToChunk(object chunk, int[] heights, int chunkSize = 16)
            => TryApplyHeightsToChunk(chunk, heights, landcover: null, chunkSize);

        public static bool TryApplyHeightsToChunk(
            object chunk, int[] heights, byte[]? landcover, int chunkSize = 16)
        {
            if (chunk == null || heights == null || heights.Length < chunkSize * chunkSize)
                return false;

            var t = chunk.GetType();
            if (_cachedChunkType != t)
            {
                _cachedChunkType = t;
                _setDensityCached = FindSetDensity(t);
                // Prefer full SetBlock so mesh/collision dirty flags run after inject.
                _setBlockCached = FindSetBlock(t) ?? FindSetBlockRaw(t);
                _setHeight = FindSetHeight(t);
            }
            MethodInfo? setDensity = _setDensityCached;
            MethodInfo? setBlock = _setBlockCached;
            if (setDensity == null && setBlock == null)
                return false;

            ResolveTerrainBlocks();

            int columnMax = EngineHeight.EngineHeightMod.AllocatableColumnMaxY;
            columnMax = Math.Max(2, Math.Min(columnMax, HeightCompress.EngineTargetMaxY));
            int dualMax = Math.Min(EffectiveFullDualFillMaxSurface(), columnMax - 1);

            object? solidDens = null;
            object? airDens = null;
            if (setDensity != null)
            {
                Type densType = setDensity.GetParameters()[3].ParameterType;
                solidDens = Convert.ChangeType((sbyte)(-1), densType);
                airDens = Convert.ChangeType((sbyte)127, densType);
            }

            object[]? heightArgs = _setHeight != null ? new object[3] : null;
            bool heightIsByte = false;
            if (_setHeight != null)
            {
                var hps = _setHeight.GetParameters();
                heightIsByte = hps.Length >= 3 && hps[2].ParameterType == typeof(byte);
            }
            object[]? blockArgs = setBlock != null ? new object[4] : null;
            object[]? densArgs = setDensity != null ? new object[4] : null;

            bool any = false;
            int failures = 0;
            for (int z = 0; z < chunkSize; z++)
            {
                for (int x = 0; x < chunkSize; x++)
                {
                    int surface = heights[z * chunkSize + x];
                    surface = Math.Max(1, Math.Min(columnMax - 1, surface));
                    byte lc = landcover != null && landcover.Length > z * chunkSize + x
                        ? landcover[z * chunkSize + x]
                        : (byte)255;
                    object solid = PickSolidBlock(lc) ?? _solidBlock ?? _airBlock!;

                    if (_setHeight != null && heightArgs != null)
                    {
                        try
                        {
                            heightArgs[0] = x;
                            heightArgs[1] = z;
                            heightArgs[2] = heightIsByte
                                ? (object)(byte)Math.Min(255, surface)
                                : surface;
                            _setHeight.Invoke(chunk, heightArgs);
                        }
                        catch { /* optional */ }
                    }

                    // dualFull: full solid [0,surface). Tall: crust+plug only (never full-column Reflect to Everest).
                    bool dualFull = surface <= dualMax;
                    int crustLo = dualFull ? 0 : Math.Max(0, surface - TallCrustDepth);
                    // Air-clear stock RWG above surface (capped; not full YDim).
                    int airClearHi = Math.Min(columnMax - 1, surface + 128);
                    int yWriteLo = dualFull ? 0 : Math.Min(crustLo, 4);
                    // Density+blocks share the same write band for tall (crust+plug+air), not 0..surface.
                    int yWriteHi = airClearHi;

                    void WriteColumnCell(int y, bool solidCell)
                    {
                        if (setDensity != null && densArgs != null && solidDens != null && airDens != null)
                        {
                            try
                            {
                                densArgs[0] = x;
                                densArgs[1] = y;
                                densArgs[2] = z;
                                densArgs[3] = solidCell ? solidDens : airDens;
                                setDensity.Invoke(chunk, densArgs);
                                any = true;
                            }
                            catch
                            {
                                failures++;
                            }
                        }
                        if (setBlock != null && blockArgs != null && solid != null && _airBlock != null)
                        {
                            try
                            {
                                blockArgs[0] = x;
                                blockArgs[1] = y;
                                blockArgs[2] = z;
                                blockArgs[3] = solidCell ? solid : _airBlock;
                                setBlock.Invoke(chunk, blockArgs);
                                any = true;
                            }
                            catch
                            {
                                failures++;
                            }
                        }
                    }

                    if (dualFull)
                    {
                        for (int y = 0; y <= yWriteHi; y++)
                            WriteColumnCell(y, solidCell: y < surface);
                    }
                    else
                    {
                        // Bedrock plug y=0..3
                        for (int y = 0; y < 4; y++)
                            WriteColumnCell(y, solidCell: true);
                        // Crust under surface
                        for (int y = crustLo; y < surface; y++)
                        {
                            if (y < 4) continue; // already plug
                            WriteColumnCell(y, solidCell: true);
                        }
                        // Air clear above surface
                        for (int y = surface; y <= yWriteHi; y++)
                            WriteColumnCell(y, solidCell: false);
                    }
                    if (failures > 64 && !any)
                        return false;
                }
            }
            return any;
        }

        public static bool TryApplyHeightsToChunk(object chunk, byte[] heights, int chunkSize = 16)
        {
            if (heights == null) return false;
            var ints = new int[heights.Length];
            for (int i = 0; i < heights.Length; i++)
                ints[i] = heights[i];
            return TryApplyHeightsToChunk(chunk, ints, null, chunkSize);
        }

        static object? PickSolidBlock(byte landcover)
        {
            // Map coarse landcover → terrain block when resolved.
            switch (landcover)
            {
                case 0:
                case 1:
                    return _solidBlock; // water underlay still needs solid floor under sea
                case 2:
                case 10:
                    return _snowBlock ?? _solidBlock;
                case 5:
                case 11:
                    return _sandBlock ?? _dirtBlock ?? _solidBlock;
                case 3:
                    return _dirtBlock ?? _solidBlock;
                default:
                    return _dirtBlock ?? _solidBlock;
            }
        }

        static MethodInfo? FindSetDensity(Type t)
        {
            foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (m.Name != "SetDensity") continue;
                var ps = m.GetParameters();
                if (ps.Length == 4
                    && ps[0].ParameterType == typeof(int)
                    && ps[1].ParameterType == typeof(int)
                    && ps[2].ParameterType == typeof(int))
                    return m;
            }
            return null;
        }

        static MethodInfo? FindSetBlock(Type t)
        {
            foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (m.Name != "SetBlock") continue;
                var ps = m.GetParameters();
                if (ps.Length == 4
                    && ps[0].ParameterType == typeof(int)
                    && ps[1].ParameterType == typeof(int)
                    && ps[2].ParameterType == typeof(int)
                    && ps[3].ParameterType.Name.IndexOf("BlockValue", StringComparison.OrdinalIgnoreCase) >= 0)
                    return m;
            }
            return null;
        }

        /// <summary>Prefer SetBlockRaw when present (fewer side effects / faster than full SetBlock).</summary>
        static MethodInfo? FindSetBlockRaw(Type t)
        {
            foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (m.Name != "SetBlockRaw") continue;
                var ps = m.GetParameters();
                if (ps.Length == 4
                    && ps[0].ParameterType == typeof(int)
                    && ps[1].ParameterType == typeof(int)
                    && ps[2].ParameterType == typeof(int))
                    return m;
            }
            return null;
        }

        static MethodInfo? FindSetHeight(Type t)
        {
            foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (m.Name != "SetHeight") continue;
                var ps = m.GetParameters();
                if (ps.Length == 3
                    && ps[0].ParameterType == typeof(int)
                    && ps[1].ParameterType == typeof(int))
                    return m;
            }
            return null;
        }

        static void ResolveTerrainBlocks()
        {
            if (_blocksResolved) return;
            _blocksResolved = true;
            try
            {
                Type? blockType = null;
                foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                {
                    if (!string.Equals(asm.GetName().Name, "Assembly-CSharp", StringComparison.OrdinalIgnoreCase))
                        continue;
                    try
                    {
                        blockType = asm.GetType("Block")
                            ?? Array.Find(asm.GetTypes(), x => x != null && x.Name == "Block");
                    }
                    catch (ReflectionTypeLoadException ex)
                    {
                        blockType = Array.Find(ex.Types ?? Array.Empty<Type>(), x => x != null && x.Name == "Block");
                    }
                    break;
                }
                if (blockType == null) return;

                MethodInfo? getBv = null;
                foreach (var m in blockType.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
                {
                    if (m.Name != "GetBlockValue") continue;
                    var ps = m.GetParameters();
                    if (ps.Length >= 1 && ps[0].ParameterType == typeof(string))
                    {
                        getBv = m;
                        break;
                    }
                }
                if (getBv == null) return;

                object? InvokeName(string name)
                {
                    var ps = getBv!.GetParameters();
                    if (ps.Length == 1)
                        return getBv.Invoke(null, new object[] { name });
                    if (ps.Length >= 2 && ps[1].ParameterType == typeof(bool))
                        return getBv.Invoke(null, new object[] { name, true });
                    return getBv.Invoke(null, new object[] { name });
                }

                object? TryNames(params string[] names)
                {
                    foreach (var solidName in names)
                    {
                        try
                        {
                            var bv = InvokeName(solidName);
                            if (bv != null) return bv;
                        }
                        catch { /* next */ }
                    }
                    return null;
                }

                _solidBlock = TryNames("terrStone", "terrDirt", "terrainFiller", "terrGrass");
                _dirtBlock = TryNames("terrDirt", "terrGrass", "terrStone");
                _snowBlock = TryNames("terrSnow", "terrIce", "terrDirt");
                _sandBlock = TryNames("terrSand", "terrDirt");
                _airBlock = TryNames("air", "Air");
                if (_airBlock == null && _solidBlock != null)
                {
                    var bvType = _solidBlock.GetType();
                    var airField = bvType.GetField("Air", BindingFlags.Static | BindingFlags.Public);
                    if (airField != null) _airBlock = airField.GetValue(null);
                }

                ModApi.Log(
                    _solidBlock != null && _airBlock != null
                        ? "Height inject: solid+air BlockValue ready (landcover-aware columns)."
                        : "Height inject: BlockValue partial — density-only columns.");
            }
            catch (Exception ex)
            {
                ModApi.Log($"Height inject BlockValue resolve failed: {ex.Message}");
            }
        }
    }
}
