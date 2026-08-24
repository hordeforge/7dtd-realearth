using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;

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
        /// <summary>
        /// Serializes lazy init of the reflection caches above: chunk gen runs on the
        /// GenerateChunks thread while origin-slide reinject runs on the main thread.
        /// Without this, one thread can see _cachedChunkType/_blocksResolved set before
        /// the cached methods/blocks are published and skip injection for that chunk
        /// (permanent ocean columns baked into the save).
        /// </summary>
        static readonly object _initLock = new object();
        // Counters are cross-thread: the gen thread increments inject stats while the
        // main thread resets them at WorldReady and adds reinject totals. Plain
        // read-modify-write would lose updates; Interlocked + Volatile.Read keeps them honest.
        static int _sessionPeakHeight;
        static int _sessionInjectCount;
        static int _sessionBlocksApplied;
        static int _sessionReinjectedChunks;

        /// <summary>Highest maxH seen this session (for dedicated gates / diagnostics).</summary>
        public static int SessionPeakHeight => Volatile.Read(ref _sessionPeakHeight);
        public static int SessionInjectCount => Volatile.Read(ref _sessionInjectCount);
        public static int SessionBlocksApplied => Volatile.Read(ref _sessionBlocksApplied);
        /// <summary>Loaded chunks rewritten after origin slides (SoloSlide desync closure).</summary>
        public static int SessionReinjectedChunks => Volatile.Read(ref _sessionReinjectedChunks);

        /// <summary>Reset per-world inject counters (WorldReady / reinject reset).</summary>
        public static void ResetSessionCounters()
        {
            Interlocked.Exchange(ref _sessionPeakHeight, 0);
            Interlocked.Exchange(ref _sessionInjectCount, 0);
            Interlocked.Exchange(ref _sessionBlocksApplied, 0);
            Interlocked.Exchange(ref _sessionReinjectedChunks, 0);
            Volatile.Write(ref _injectLogBudget, 24);
        }

        /// <summary>Atomic max for the session peak (gen thread only writer, reset races WorldReady).</summary>
        static void RaiseSessionPeak(int maxH)
        {
            int cur = Volatile.Read(ref _sessionPeakHeight);
            while (maxH > cur)
            {
                int prev = Interlocked.CompareExchange(ref _sessionPeakHeight, maxH, cur);
                if (prev == cur) break;
                cur = prev;
            }
        }

        /// <summary>
        /// Consume one log-budget slot. Interlocked because the gen thread (OnChunkGenerated)
        /// and the main thread (origin-slide reinject) share the budget; a plain check-then-
        /// decrement can both pass and over-log.
        /// </summary>
        static bool ConsumeInjectLogBudget() => Interlocked.Decrement(ref _injectLogBudget) >= 0;

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
            var landcover = new byte[n];
            ChunkTerrainSampler.FillChunkColumns(
                session, streamer, ModApi.Config, blockX, blockZ,
                ChunkTerrainSampler.VanillaChunkSize, heights, landcover);

            bool applied = false;
            int appliedColumns = 0;
            if (chunkObj != null)
                applied = TryApplyHeightsToChunk(chunkObj, heights, landcover, ChunkTerrainSampler.VanillaChunkSize, out appliedColumns);

            // Runtime density/POI stamps for urban cells (budgeted).
            try
            {
                RuntimePoiInject.OnChunkGenerated(chunkX, chunkZ);
            }
            catch { /* never break inject */ }

            // Only count successful column rewrites (null chunk / apply miss do not inflate gates).
            int maxH = 0;
            for (int i = 0; i < heights.Length; i++)
                if (heights[i] > maxH) maxH = heights[i];
            if (applied)
            {
                Interlocked.Increment(ref _sessionInjectCount);
                // Count real applied columns, not one per chunk.
                Interlocked.Add(ref _sessionBlocksApplied, appliedColumns);
                RaiseSessionPeak(maxH);
            }
            int mid = heights[heights.Length / 2];

            if (ConsumeInjectLogBudget())
            {
                byte lc = landcover[landcover.Length / 2];
                ModApi.Log(
                    $"Height inject chunk=({chunkX},{chunkZ}) earth=({ex},{ez}) " +
                    $"midH={mid} maxH={maxH} sessionPeak={SessionPeakHeight} " +
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
        /// Tall columns above this: bedrock plug + block crust + air clear only;
        /// the interior below the crust is intentionally left untouched
        /// (documented residual: docs/realearth-runtime.md "Intentional hollow").
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
        /// Above that: bedrock plug + solid crust under the surface + air clear.
        /// The interior between plug and crust is intentionally NOT written
        /// (never full-column Reflect to Everest; see docs/realearth-runtime.md).
        /// </summary>
        public static bool TryApplyHeightsToChunk(object chunk, int[] heights, int chunkSize = 16)
            => TryApplyHeightsToChunk(chunk, heights, landcover: null, chunkSize, out _);

        public static bool TryApplyHeightsToChunk(
            object chunk, int[] heights, byte[]? landcover, int chunkSize)
            => TryApplyHeightsToChunk(chunk, heights, landcover, chunkSize, out _);

        /// <summary>
        /// Core apply. appliedColumns counts columns with at least one successful
        /// density/block write; it is returned per call instead of stored in a shared
        /// static because the gen thread and main-thread reinject can run concurrently.
        /// </summary>
        public static bool TryApplyHeightsToChunk(
            object chunk, int[] heights, byte[]? landcover, int chunkSize, out int appliedColumns)
        {
            appliedColumns = 0;
            if (chunk == null || heights == null || heights.Length < chunkSize * chunkSize)
                return false;

            // Resolve reflection caches under one lock (gen thread + main-thread reinject).
            // Everything read afterwards is copied to locals so no unlocked static reads race
            // a first-time resolve on the other thread.
            MethodInfo? setDensity;
            MethodInfo? setBlock;
            MethodInfo? setHeight;
            object? solidBlock;
            object? dirtBlock;
            object? snowBlock;
            object? sandBlock;
            object? airBlock;
            lock (_initLock)
            {
                var t = chunk.GetType();
                if (_cachedChunkType != t)
                {
                    _cachedChunkType = t;
                    _setDensityCached = FindSetDensity(t);
                    // Prefer full SetBlock so mesh/collision dirty flags run after inject.
                    _setBlockCached = FindSetBlock(t) ?? FindSetBlockRaw(t);
                    _setHeight = FindSetHeight(t);
                }
                ResolveTerrainBlocksLocked();
                setDensity = _setDensityCached;
                setBlock = _setBlockCached;
                setHeight = _setHeight;
                solidBlock = _solidBlock;
                dirtBlock = _dirtBlock;
                snowBlock = _snowBlock;
                sandBlock = _sandBlock;
                airBlock = _airBlock;
            }
            if (setDensity == null && setBlock == null)
                return false;

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

            object[]? heightArgs = setHeight != null ? new object[3] : null;
            bool heightIsByte = false;
            if (setHeight != null)
            {
                var hps = setHeight.GetParameters();
                heightIsByte = hps.Length >= 3 && hps[2].ParameterType == typeof(byte);
            }
            object[]? blockArgs = setBlock != null ? new object[4] : null;
            object[]? densArgs = setDensity != null ? new object[4] : null;

            bool any = false;
            int columns = 0;
            int failures = 0;
            for (int z = 0; z < chunkSize; z++)
            {
                for (int x = 0; x < chunkSize; x++)
                {
                    bool colAny = false;
                    int surface = heights[z * chunkSize + x];
                    surface = Math.Max(1, Math.Min(columnMax - 1, surface));
                    byte lc = landcover != null && landcover.Length > z * chunkSize + x
                        ? landcover[z * chunkSize + x]
                        : (byte)255;
                    // No `!` fallback: when reflection resolved nothing (density-only builds)
                    // the block write is skipped below rather than NRE-ing mid-chunk.
                    object? solid = PickSolidBlock(lc, dirtBlock, snowBlock, sandBlock, solidBlock)
                        ?? solidBlock;

                    if (setHeight != null && heightArgs != null)
                    {
                        try
                        {
                            heightArgs[0] = x;
                            heightArgs[1] = z;
                            heightArgs[2] = heightIsByte
                                ? (object)(byte)Math.Min(255, surface)
                                : surface;
                            setHeight.Invoke(chunk, heightArgs);
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
                                colAny = true;
                            }
                            catch
                            {
                                failures++;
                            }
                        }
                        if (blockArgs != null && solid != null && airBlock != null)
                        {
                            try
                            {
                                blockArgs[0] = x;
                                blockArgs[1] = y;
                                blockArgs[2] = z;
                                blockArgs[3] = solidCell ? solid : airBlock;
                                setBlock!.Invoke(chunk, blockArgs);
                                any = true;
                                colAny = true;
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
                    if (colAny)
                        columns++;
                    if (failures > 64 && !any)
                        return false;
                }
            }
            appliedColumns = columns;
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

        /// <summary>
        /// Re-inject loaded chunks around a local block position after an origin slide.
        /// Loaded chunks keep pre-slide Earth columns until the engine regenerates them
        /// (SoloSlide mesh/voxel desync); rewrite columns in place so terrain matches the
        /// new origin immediately. SetBlock dirty flags refresh meshes. Bounded by radius
        /// and maxChunks so a slide never hitches gen. Never throws to callers.
        /// </summary>
        /// <param name="world">Engine World instance (reflection, no hard reference).</param>
        /// <param name="centerLocalXZ">Post-slide local player block coords.</param>
        public static int ReinjectLoadedChunksAround(
            object? world, int centerLocalX, int centerLocalZ,
            int radiusBlocks = 128, int maxChunks = 96)
        {
            if (world == null || !HeightModWantsInject()) return 0;
            int reinjected = 0;
            try
            {
                var chunks = FindLoadedChunkCollection(world);
                if (chunks == null) return 0;

                int ccx = EngineReflection.FloorDiv(centerLocalX, ChunkTerrainSampler.VanillaChunkSize);
                int ccz = EngineReflection.FloorDiv(centerLocalZ, ChunkTerrainSampler.VanillaChunkSize);
                int rChunks = Math.Max(1, radiusBlocks / ChunkTerrainSampler.VanillaChunkSize);

                var candidates = new List<(int dist, int cx, int cz, object chunk)>();
                foreach (var c in chunks)
                {
                    if (c == null) continue;
                    if (!TryReadChunkCoords(c, out int cx, out int cz)) continue;
                    int d = Math.Max(Math.Abs(cx - ccx), Math.Abs(cz - ccz));
                    if (d > rChunks) continue;
                    candidates.Add((d, cx, cz, c));
                }
                // Closest chunks first so the cap keeps the play area correct.
                candidates.Sort((a, b) => a.dist.CompareTo(b.dist));

                foreach (var cand in candidates)
                {
                    if (reinjected >= maxChunks) break;
                    if (ReinjectChunkObject(cand.cx, cand.cz, cand.chunk))
                        reinjected++;
                }

                if (reinjected > 0)
                {
                    Interlocked.Add(ref _sessionReinjectedChunks, reinjected);
                    if (ConsumeInjectLogBudget())
                    {
                        ModApi.Log(
                            $"Origin slide reinject: {reinjected}/{candidates.Count} loaded chunks " +
                            $"rewritten around local=({centerLocalX},{centerLocalZ}) " +
                            $"r={radiusBlocks} sessionTotal={SessionReinjectedChunks}");
                    }
                }
            }
            catch (Exception ex)
            {
                if (ConsumeInjectLogBudget())
                {
                    ModApi.Log("ReinjectLoadedChunksAround failed (non-fatal): " + ex.Message);
                }
            }
            return reinjected;
        }

        /// <summary>
        /// Rewrite one loaded chunk's columns under the current origin mapping.
        /// Same path as OnChunkGenerated minus POI stamping / gen stats (no double-count).
        /// </summary>
        static bool ReinjectChunkObject(int chunkX, int chunkZ, object chunkObj)
        {
            var session = ModApi.Session;
            var streamer = ModApi.Streamer;
            if (session == null || streamer == null || chunkObj == null) return false;

            int blockX = chunkX * ChunkTerrainSampler.VanillaChunkSize;
            int blockZ = chunkZ * ChunkTerrainSampler.VanillaChunkSize;
            session.LocalToEarth(blockX, blockZ, out int ex, out int ez);
            // Slide may have moved into tiles not yet hot; sync-load avoids stale ocean rewrite.
            streamer.EnsureHotAround(ex, ez, radius: 1, allowSyncLoad: true);

            int n = ChunkTerrainSampler.VanillaChunkSize * ChunkTerrainSampler.VanillaChunkSize;
            var heights = new int[n];
            var landcover = new byte[n];
            ChunkTerrainSampler.FillChunkColumns(
                session, streamer, ModApi.Config, blockX, blockZ,
                ChunkTerrainSampler.VanillaChunkSize, heights, landcover);
            return TryApplyHeightsToChunk(chunkObj, heights, landcover, ChunkTerrainSampler.VanillaChunkSize, out _);
        }

        /// <summary>
        /// Loaded-chunk collection on World or its ChunkManager (build-dependent).
        /// Prefers known names, then any IDictionary/IEnumerable member holding Chunk values.
        /// </summary>
        static IEnumerable? FindLoadedChunkCollection(object world)
        {
            foreach (var name in new[] { "chunkCache", "Chunks", "chunks" })
                if (TryReadMember(world, name, out var c) && c != null && CollectionHoldsChunks(c))
                    return EnumerateCollection(c);

            foreach (var mgrName in new[] { "ChunkManager", "chunkManager", "m_ChunkManager" })
            {
                if (!TryReadMember(world, mgrName, out var mgr) || mgr == null) continue;
                foreach (var name in new[] { "chunks", "chunkCache", "Chunks" })
                    if (TryReadMember(mgr, name, out var c) && c != null && CollectionHoldsChunks(c))
                        return EnumerateCollection(c);
                // Build drift fallback: first collection member whose values look like Chunks.
                const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
                foreach (var f in mgr.GetType().GetFields(flags))
                {
                    try
                    {
                        var v = f.GetValue(mgr);
                        if (v != null && CollectionHoldsChunks(v)) return EnumerateCollection(v);
                    }
                    catch { /* next */ }
                }
                foreach (var p in mgr.GetType().GetProperties(flags))
                {
                    if (p.GetIndexParameters().Length != 0) continue;
                    try
                    {
                        var v = p.GetValue(mgr, null);
                        if (v != null && CollectionHoldsChunks(v)) return EnumerateCollection(v);
                    }
                    catch { /* next */ }
                }
            }
            return null;
        }

        static bool TryReadMember(object obj, string name, out object? value)
        {
            value = null;
            try
            {
                const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
                var f = obj.GetType().GetField(name, flags);
                if (f != null) { value = f.GetValue(obj); return true; }
                var p = obj.GetType().GetProperty(name, flags);
                if (p != null && p.GetIndexParameters().Length == 0)
                {
                    value = p.GetValue(obj, null);
                    return true;
                }
            }
            catch { /* miss */ }
            return false;
        }

        /// <summary>Peek one element to confirm the collection stores engine Chunk objects.</summary>
        static bool CollectionHoldsChunks(object coll)
        {
            try
            {
                foreach (var item in EnumerateCollection(coll))
                {
                    if (item == null) continue;
                    return item.GetType().Name.IndexOf("Chunk", StringComparison.OrdinalIgnoreCase) >= 0;
                }
            }
            catch { /* ignore */ }
            return false;
        }

        static IEnumerable EnumerateCollection(object coll)
        {
            if (coll is IDictionary dict)
            {
                foreach (DictionaryEntry de in dict)
                    yield return de.Value!;
                yield break;
            }
            if (coll is IEnumerable en)
            {
                foreach (var item in en)
                    yield return item;
            }
        }

        /// <summary>Chunk grid coords via common field/property names (build-dependent).</summary>
        static bool TryReadChunkCoords(object chunk, out int cx, out int cz)
        {
            cx = cz = 0;
            bool hasX = false;
            bool hasZ = false;
            foreach (var name in new[] { "chunkX", "ChunkX", "X" })
                if (ReflectCache.TryReadIntMember(chunk, name, out cx)) { hasX = true; break; }
            foreach (var name in new[] { "chunkZ", "ChunkZ", "Z" })
                if (ReflectCache.TryReadIntMember(chunk, name, out cz)) { hasZ = true; break; }
            return hasX && hasZ;
        }

        /// <summary>
        /// Map coarse landcover → terrain block from the caller's locked-init snapshot
        /// (no unlocked static reads on the gen/reinject threads).
        /// </summary>
        static object? PickSolidBlock(
            byte landcover,
            object? dirtBlock,
            object? snowBlock,
            object? sandBlock,
            object? solidBlock)
        {
            // Map coarse landcover codes to terrain blocks when resolved.
            switch (landcover)
            {
                case 0:
                case 1:
                    return solidBlock; // water underlay still needs solid floor under sea
                case 2:
                case 10:
                    return snowBlock ?? solidBlock;
                case 5:
                case 11:
                    return sandBlock ?? dirtBlock ?? solidBlock;
                case 3:
                    return dirtBlock ?? solidBlock;
                default:
                    return dirtBlock ?? solidBlock;
            }
        }

        /// <summary>
        /// Instance method by name whose first `leadingInts` parameters are ints
        /// (the X/Z/Y prefix every engine block-write API shares).
        /// </summary>
        static MethodInfo? FindSetterByIntParams(
            Type t, string name, int paramCount, int leadingInts,
            Func<ParameterInfo[], bool>? extra = null)
        {
            foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (m.Name != name) continue;
                var ps = m.GetParameters();
                if (ps.Length != paramCount) continue;
                bool intsMatch = true;
                for (int i = 0; i < leadingInts; i++)
                {
                    if (ps[i].ParameterType != typeof(int)) { intsMatch = false; break; }
                }
                if (!intsMatch) continue;
                if (extra != null && !extra(ps)) continue;
                return m;
            }
            return null;
        }

        static MethodInfo? FindSetDensity(Type t) => FindSetterByIntParams(t, "SetDensity", 4, 3);

        static MethodInfo? FindSetBlock(Type t) =>
            FindSetterByIntParams(t, "SetBlock", 4, 3,
                ps => ps[3].ParameterType.Name.IndexOf("BlockValue", StringComparison.OrdinalIgnoreCase) >= 0);

        /// <summary>Fallback when full SetBlock is absent (raw write skips mesh dirty flags).</summary>
        static MethodInfo? FindSetBlockRaw(Type t) => FindSetterByIntParams(t, "SetBlockRaw", 4, 3);

        static MethodInfo? FindSetHeight(Type t) => FindSetterByIntParams(t, "SetHeight", 3, 2);

        /// <summary>Caller holds _initLock. Resolve terrain BlockValues once per process.</summary>
        static void ResolveTerrainBlocksLocked()
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
