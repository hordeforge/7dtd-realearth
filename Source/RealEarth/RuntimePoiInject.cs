using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Threading;

namespace RealEarth
{
    /// <summary>
    /// Runtime density/POI stamps near the player from settlements catalog.
    /// Mirrors tools/realearth/density.py planning (band, surface Y, DensityBudget).
    /// Placement is best-effort via PrefabManager reflection; only successful places
    /// consume budget (failed places may retry).
    /// </summary>
    public static class RuntimePoiInject
    {
        static readonly HashSet<string> _placed = new HashSet<string>(StringComparer.Ordinal);
        static readonly Dictionary<string, int> _failCount = new Dictionary<string, int>(StringComparer.Ordinal);
        // Soft gap 23: stock trader_* prefabs in city/town pools so real settlements
        // can host traders (quest geography still open; placement is best-effort).
        // TraderPools guarantee a trader stamp for metro/large_city/town; PrefabPools
        // still supply non-trader filler when PreferTraderStamp is off.
        static readonly Dictionary<string, string[]> PrefabPools = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
        {
            ["metro"] = new[] { "trader_jen", "trader_bob", "downtown_building_04", "commercial_strip_08", "gas_station_05", "house_modern_15" },
            ["large_city"] = new[] { "trader_joel", "trader_hugh", "downtown_strip_06", "commercial_site_02", "gas_station_03", "house_modern_10" },
            ["town"] = new[] { "trader_rekt", "commercial_strip_10", "gas_station_01", "house_modern_05", "church_01" },
            ["village"] = new[] { "gas_station_01", "house_country_01", "cabin_01", "farm_11" },
            ["hamlet"] = new[] { "cabin_02", "house_old_cottage_01", "barn_01", "abandoned_house_01" },
            ["rural_scatter"] = new[] { "cabin_06", "farm_19", "abandoned_house_03" },
        };

        static readonly Dictionary<string, string[]> TraderPools = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
        {
            ["metro"] = new[] { "trader_jen", "trader_bob" },
            ["large_city"] = new[] { "trader_joel", "trader_hugh" },
            ["town"] = new[] { "trader_rekt" },
        };

        const int MaxPlaceFails = 5;

        /// <summary>Log slots for the whole stamp path (shared by every pass).</summary>
        const int StampLogSlots = 12;

        /// <summary>Per-chunk stamp budget key: both stamp paths must agree on it.</summary>
        static string ChunkKey(int chunkX, int chunkZ)
            => chunkX.ToString(CultureInfo.InvariantCulture) + ":" +
               chunkZ.ToString(CultureInfo.InvariantCulture);

        /// <summary>Session-wide stamp cap from config, clamped to the density default.</summary>
        static int MaxAreaStamps(RealEarthConfig cfg)
            => DensityBudget.ClampPrefabsInArea(
                Math.Max(1, cfg.RuntimePoiMaxPerArea),
                DensityBudget.DefaultMaxPrefabsPerKm2);

        /// <summary>
        /// Gates all mutable stamp state below. TickPlayer runs on the main thread while
        /// OnChunkGenerated runs on the chunk-generation thread; unsynchronized
        /// HashSet/Dictionary mutation corrupts buckets, and unlocked budget checks lose
        /// updates (double stamps or stranded budget). Reset/OnOriginSlide clear these
        /// collections from the main thread, so they take the same gate. The tick
        /// throttle is the one exception: it is Interlocked (TryClaimTickThrottle)
        /// instead of gated, so skipped ticks never block on this lock.
        /// </summary>
        static readonly object _stampGate = new object();

        /// <summary>
        /// Ticks skipped before the next stamp pass. Reset/OnOriginSlide clear it from
        /// another thread's path, so the read-modify-write goes through Interlocked
        /// (see TryClaimTickThrottle) instead of a plain check-then-decrement.
        /// </summary>
        static int _tickThrottle;
        /// <summary>Ticks between player-tick stamp passes.</summary>
        const int TickThrottleTicks = 40;
        /// <summary>
        /// Log slots for the stamp path. LogBudget, not a bare counter: a refused line
        /// is counted, and `reinject` reports that count, so a missing "no prefab
        /// manager" line cannot read as a city pass that never had a problem.
        /// </summary>
        static readonly LogBudget _logBudget = new LogBudget(StampLogSlots);
        static int _sessionStamps;
        static List<CityMapLabels.Place>? _placesCache;
        static readonly Dictionary<string, int> _chunkCounts = new Dictionary<string, int>(StringComparer.Ordinal);

        /// <summary>Log slots the stamp path refused to print; `reinject` prints it.</summary>
        public static long SuppressedLogLines => _logBudget.Suppressed;

        /// <summary>
        /// True when this call owns the next stamp pass. Kept off _stampGate so the
        /// ~39 skipped ticks per pass never queue behind a chunk-generation stamp
        /// (prefab placement and sleeper re-pin run under that gate).
        ///
        /// The counter is "ticks left until the next pass"; 0 (every reset site) means
        /// a pass is due now. Compare-exchange keeps the claim exclusive when two
        /// threads reach it on the same tick, which a plain decrement-then-increment
        /// did not: giving a slot back before the check let the counter oscillate
        /// between 0 and -1 and the claim branch was never taken.
        /// </summary>
        static bool TryClaimTickThrottle()
        {
            while (true)
            {
                int left = Volatile.Read(ref _tickThrottle);
                int next = left > 0 ? left - 1 : TickThrottleTicks - 1;
                if (Interlocked.CompareExchange(ref _tickThrottle, next, left) == left)
                    return left <= 0;
            }
        }

        public static void Reset()
        {
            lock (_stampGate)
            {
                _placed.Clear();
                _failCount.Clear();
                _chunkCounts.Clear();
                _placesCache = null;
                _tickThrottle = 0;
                _sessionStamps = 0;
                _logBudget.Reset(StampLogSlots);
            }
        }

        /// <summary>Memoized session-local coords (CityMapLabels.Place cache); see LonLatToLocalCached.</summary>
        static void PlaceLocal(WorldSession session, CityMapLabels.Place p, out int cx, out int cz)
            => CityMapLabels.LonLatToLocalCached(session, p, out cx, out cz);

        /// <summary>
        /// After origin slide: do not re-stamp (chunk blocks are not remapped; re-plan would
        /// duplicate POIs at new locals while ghosts remain). Keep _placed; clear budgets only.
        /// </summary>
        public static void OnOriginSlide()
        {
            lock (_stampGate)
            {
                _chunkCounts.Clear();
                _tickThrottle = 0;
                InvalidateLocalCache();
                // Keep _placed / _sessionStamps so we do not double-stamp after slide.
            }
        }

        static void InvalidateLocalCache()
        {
            if (_placesCache == null) return;
            foreach (var p in _placesCache)
                p.LocalValid = false;
        }

        /// <summary>
        /// Origin moved: drop the place-local memo and the tick throttle. Called from
        /// WorldSession.SetOrigin so every origin write (slide, snapshot restore,
        /// `resession load`) re-stamps at the new local positions. Budgets and
        /// _placed are untouched: a moved window must not re-stamp chunks that
        /// already hold their POIs.
        /// </summary>
        public static void InvalidateOriginDerivedCache()
        {
            lock (_stampGate)
            {
                InvalidateLocalCache();
                _tickThrottle = 0;
            }
        }

        /// <summary>
        /// The stamp path keeps its own memoized copy of the settlements catalog
        /// (see _placesCache), separate from the one CityMapLabels holds. Both
        /// read the same settlements.json, so every catalog reset must drop this
        /// copy too: otherwise the label pass reloads the pack while stamping
        /// keeps planning from the list read before the reset, and the two passes
        /// disagree on which places exist. Budgets and _placed stay: a place that
        /// is already stamped in the world must not be stamped again because the
        /// catalog was re-read.
        /// </summary>
        public static void InvalidatePlacesCatalog()
        {
            lock (_stampGate)
            {
                _placesCache = null;
            }
        }

        /// <summary>Player tick: stamp nearby city cores under DensityBudget.</summary>
        public static void TickPlayer(int playerLocalX, int playerLocalZ)
        {
            var cfg = ModApi.Config;
            if (cfg == null || !cfg.EnableRuntimePoiInject)
                return;
            if (!TryClaimTickThrottle())
                return;

            try
            {
                lock (_stampGate)
                {
                    var session = ModApi.Session;
                    if (session == null) return;
                    if (_placesCache == null)
                        _placesCache = CityMapLabels.LoadPlaces();
                    if (_placesCache == null || _placesCache.Count == 0) return;

                    int maxArea = MaxAreaStamps(cfg);
                    if (_sessionStamps >= maxArea)
                        return;

                    float discoverScale = cfg.CityMapDiscoverRadiusScale > 0.05f
                        ? cfg.CityMapDiscoverRadiusScale
                        : 1f;

                    foreach (var p in _placesCache)
                    {
                        if (_sessionStamps >= maxArea) break;
                        if (string.IsNullOrEmpty(p.Name)) continue;
                        if (_placed.Contains(p.Name)) continue;
                        if (_failCount.TryGetValue(p.Name, out int fails) && fails >= MaxPlaceFails)
                            continue;

                        PlaceLocal(session, p, out int cx, out int cz);
                        long dx = (long)playerLocalX - cx;
                        long dz = (long)playerLocalZ - cz;
                        long distSq = dx * dx + dz * dz;
                        // Original gate: dist <= edge * 1.5 (squared to skip the sqrt).
                        double edge = CityMapLabels.ScaledEdgeRadiusBlocks(
                            CityMapLabels.ResolveEdgeRadiusBlocks(p), discoverScale);
                        double reach = edge * 1.5;
                        if (distSq > reach * reach)
                            continue;

                        string chunkKey = ChunkKey(EngineReflection.FloorDiv(cx, ChunkTerrainSampler.VanillaChunkSize),
                                                  EngineReflection.FloorDiv(cz, ChunkTerrainSampler.VanillaChunkSize));
                        StampWithBudget(session, p, cx, cz, chunkKey, playerLocalX, playerLocalZ);
                    }
                }
            }
            catch (Exception ex)
            {
                if (_logBudget.Allow())
                {
                    ModLog.LogError("RuntimePoiInject: " + ex.GetType().Name + ": " + ex.Message);
                }
            }
        }

        /// <summary>
        /// Chunk inject: only consider places whose local center falls in this chunk
        /// (O(places) once, not full TickPlayer storm per chunk).
        /// </summary>
        public static void OnChunkGenerated(int chunkX, int chunkZ)
        {
            var cfg = ModApi.Config;
            if (cfg == null || !cfg.EnableRuntimePoiInject) return;
            var session = ModApi.Session;
            if (session == null) return;
            try
            {
                lock (_stampGate)
                {
                    if (_placesCache == null)
                        _placesCache = CityMapLabels.LoadPlaces();
                    if (_placesCache == null || _placesCache.Count == 0) return;

                    int maxArea = MaxAreaStamps(cfg);
                    if (_sessionStamps >= maxArea) return;

                    int minX = chunkX * ChunkTerrainSampler.VanillaChunkSize;
                    int minZ = chunkZ * ChunkTerrainSampler.VanillaChunkSize;
                    int maxX = minX + ChunkTerrainSampler.VanillaChunkSize;
                    int maxZ = minZ + ChunkTerrainSampler.VanillaChunkSize;
                    string chunkKey = ChunkKey(chunkX, chunkZ);

                    foreach (var p in _placesCache)
                    {
                        if (_sessionStamps >= maxArea) break;
                        if (string.IsNullOrEmpty(p.Name) || _placed.Contains(p.Name)) continue;
                        if (_failCount.TryGetValue(p.Name, out int fails) && fails >= MaxPlaceFails)
                            continue;

                        PlaceLocal(session, p, out int cx, out int cz);
                        if (cx < minX || cx >= maxX || cz < minZ || cz >= maxZ)
                            continue;

                        StampWithBudget(session, p, cx, cz, chunkKey);
                    }
                }
            }
            catch (Exception ex)
            {
                if (_logBudget.Allow())
                {
                    ModLog.LogError("RuntimePoiInject chunk: " + ex.GetType().Name + ": " + ex.Message);
                }
            }
        }

        /// <summary>
        /// Shared stamp tail for TickPlayer / OnChunkGenerated (caller holds _stampGate):
        /// distance-LOD gate, chunk-budget gate, place attempt, sleeper Y re-pin, accounting.
        /// playerLocalX/Z &lt; int.MinValue/2 means "no player distance" (chunk path): skip LOD drop.
        /// </summary>
        static void StampWithBudget(
            WorldSession session,
            CityMapLabels.Place p,
            int cx,
            int cz,
            string chunkKey,
            int playerLocalX = int.MinValue / 2,
            int playerLocalZ = int.MinValue / 2)
        {
            int distBlocks = -1;
            bool hasPlayer = playerLocalX > int.MinValue / 4;
            if (hasPlayer)
            {
                distBlocks = DensityBudget.DistanceBlocks(playerLocalX, playerLocalZ, cx, cz);
                if (!DensityBudget.AllowStampAtDistance(distBlocks))
                    return;
            }

            int inChunk = _chunkCounts.TryGetValue(chunkKey, out int c) ? c : 0;
            if (DensityBudget.ClampPrefabsInChunk(inChunk + 1) <= inChunk)
                return;
            if (TryStampPlace(session, p, cx, cz, distBlocks))
            {
                _placed.Add(p.Name);
                _chunkCounts[chunkKey] = inChunk + 1;
                _sessionStamps++;
            }
            else
            {
                _failCount[p.Name] = (_failCount.TryGetValue(p.Name, out int fails) ? fails : 0) + 1;
            }
        }

        static bool TryStampPlace(WorldSession session, CityMapLabels.Place p, int localX, int localZ, int distBlocks = -1)
        {
            int surface = ChunkTerrainSampler.SampleGameHeightInt(localX, localZ);
            int y = StampSurfaceY.PrefabRootY(surface, foundationOffsetBlocks: 0);
            string band = string.IsNullOrEmpty(p.Band) ? BandFromPop(p.Population) : p.Band;
            string prefabName = PickPrefab(band, p.Name);

            bool placed = TryPlacePrefabReflection(prefabName, localX, y, localZ);
            if (placed)
            {
                float weight = distBlocks < 0 ? 1f : DensityBudget.SleeperWeight(distBlocks);
                if (weight > 0f)
                    TryRepinSleeperVolumesNear(localX, localZ, StampSurfaceY.PrefabRootY(surface));
            }
            if (_logBudget.Allow())
            {
                ModLog.Log(
                    $"RuntimePoiInject: {(placed ? "placed" : "retry-later")} '{prefabName}' " +
                    $"for '{p.Name}' band={band} local=({localX},{y},{localZ}) surface={surface}" +
                    (distBlocks >= 0 ? $" dist={distBlocks}" : ""));
            }
            return placed;
        }

        /// <summary>
        /// Soft gap 16: best-effort re-pin nearby World sleeper volumes onto real
        /// surface Y. Called after POI stamps and after chunk inject. Fail soft if
        /// SleeperVolume API is missing or fields differ; never break inject/stamp.
        /// </summary>
        public static void TryRepinSleeperVolumesNear(int localX, int localZ, int sleeperY)
        {
            try
            {
                object? world = ReflectCache.GetEngineWorld();
                if (world == null) return;

                MethodInfo? getAll = null;
                foreach (var m in world.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                {
                    if (m.Name != "GetAllSleeperVolumes") continue;
                    var ps = m.GetParameters();
                    if (ps.Length == 1) { getAll = m; break; }
                }
                if (getAll == null) return;

                // Prefer List&lt;(int,SleeperVolume)&gt; or List&lt;KeyValuePair&lt;int,SleeperVolume&gt;&gt; or List&lt;SleeperVolume&gt;.
                Type listArg = getAll.GetParameters()[0].ParameterType;
                object? list = Activator.CreateInstance(listArg);
                if (list == null) return;
                getAll.Invoke(world, new object[] { list });

                PropertyInfo? countProp = listArg.GetProperty("Count");
                PropertyInfo? itemProp = listArg.GetProperty("Item");
                if (countProp == null || itemProp == null) return;
                int count = (int)(countProp.GetValue(list) ?? 0);
                if (count <= 0) return;

                const int radius = 48;
                int pinned = 0;
                for (int i = 0; i < count; i++)
                {
                    object? entry = itemProp.GetValue(list, new object[] { i });
                    if (entry == null) continue;
                    object? vol = entry;
                    // Tuple / KVP: take Item2 or Value if present.
                    var t = entry.GetType();
                    FieldInfo? item2 = t.GetField("Item2") ?? t.GetField("value") ?? t.GetField("Value");
                    PropertyInfo? item2p = t.GetProperty("Item2") ?? t.GetProperty("Value");
                    if (item2 != null) vol = item2.GetValue(entry);
                    else if (item2p != null) vol = item2p.GetValue(entry);
                    if (vol == null) continue;

                    if (!TryGetSleeperBox(vol, out int minX, out int minY, out int minZ, out int maxX, out int maxY, out int maxZ))
                        continue;
                    int cx = (minX + maxX) / 2;
                    int cz = (minZ + maxZ) / 2;
                    long dx = (long)cx - localX;
                    long dz = (long)cz - localZ;
                    if (dx * dx + dz * dz > (long)radius * radius) continue;

                    int dy = sleeperY - minY;
                    if (dy == 0) continue;
                    if (!TrySetSleeperBox(vol, minX, minY + dy, minZ, maxX, maxY + dy, maxZ))
                        continue;
                    pinned++;
                }
                if (pinned > 0 && _logBudget.Allow())
                    ModLog.Log($"RuntimePoiInject: sleeper Y re-pin count={pinned} near=({localX},{localZ}) y={sleeperY}");
            }
            catch (Exception ex)
            {
                if (_logBudget.Allow())
                    ModLog.Log($"RuntimePoiInject: sleeper Y skip ({ex.GetType().Name}: {ex.Message})");
            }
        }

        static bool TryGetSleeperBox(object vol, out int minX, out int minY, out int minZ, out int maxX, out int maxY, out int maxZ)
        {
            minX = minY = minZ = maxX = maxY = maxZ = 0;
            object? boxMin = GetMember(vol, "BoxMin") ?? GetMember(vol, "boxMin");
            object? boxMax = GetMember(vol, "BoxMax") ?? GetMember(vol, "boxMax");
            if (boxMin == null || boxMax == null) return false;
            if (!TryReadVec3i(boxMin, out minX, out minY, out minZ)) return false;
            if (!TryReadVec3i(boxMax, out maxX, out maxY, out maxZ)) return false;
            return true;
        }

        static bool TrySetSleeperBox(object vol, int minX, int minY, int minZ, int maxX, int maxY, int maxZ)
        {
            // Prefer SetMinMax(boxMin, boxMax) when present.
            MethodInfo? setMinMax = null;
            foreach (var m in vol.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (m.Name != "SetMinMax") continue;
                if (m.GetParameters().Length == 2) { setMinMax = m; break; }
            }
            if (setMinMax != null)
            {
                Type p0 = setMinMax.GetParameters()[0].ParameterType;
                Type p1 = setMinMax.GetParameters()[1].ParameterType;
                object? bmin = MakeVec3i(p0, minX, minY, minZ);
                object? bmax = MakeVec3i(p1, maxX, maxY, maxZ);
                if (bmin == null || bmax == null) return false;
                setMinMax.Invoke(vol, new object[] { bmin, bmax });
                return true;
            }

            object? boxMin = GetMember(vol, "BoxMin") ?? GetMember(vol, "boxMin");
            object? boxMax = GetMember(vol, "BoxMax") ?? GetMember(vol, "boxMax");
            if (boxMin == null || boxMax == null) return false;
            if (!TryWriteVec3i(boxMin, minX, minY, minZ)) return false;
            if (!TryWriteVec3i(boxMax, maxX, maxY, maxZ)) return false;
            return true;
        }

        static object? GetMember(object obj, string name)
        {
            var t = obj.GetType();
            return t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(obj)
                ?? t.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(obj);
        }

        static bool TryReadVec3i(object v, out int x, out int y, out int z)
        {
            x = y = z = 0;
            try
            {
                object? xv = GetMember(v, "x") ?? GetMember(v, "X");
                object? yv = GetMember(v, "y") ?? GetMember(v, "Y");
                object? zv = GetMember(v, "z") ?? GetMember(v, "Z");
                if (xv == null || yv == null || zv == null) return false;
                x = Convert.ToInt32(xv);
                y = Convert.ToInt32(yv);
                z = Convert.ToInt32(zv);
                return true;
            }
            catch { return false; }
        }

        static bool TryWriteVec3i(object v, int x, int y, int z)
        {
            try
            {
                var t = v.GetType();
                var fx = t.GetField("x", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                    ?? t.GetField("X", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                var fy = t.GetField("y", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                    ?? t.GetField("Y", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                var fz = t.GetField("z", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                    ?? t.GetField("Z", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (fx != null && fy != null && fz != null)
                {
                    fx.SetValue(v, x);
                    fy.SetValue(v, y);
                    fz.SetValue(v, z);
                    return true;
                }
                var px = t.GetProperty("x", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                    ?? t.GetProperty("X", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                var py = t.GetProperty("y", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                    ?? t.GetProperty("Y", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                var pz = t.GetProperty("z", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                    ?? t.GetProperty("Z", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (px != null && py != null && pz != null && px.CanWrite && py.CanWrite && pz.CanWrite)
                {
                    px.SetValue(v, x);
                    py.SetValue(v, y);
                    pz.SetValue(v, z);
                    return true;
                }
            }
            catch { /* fail soft */ }
            return false;
        }

        static object? MakeVec3i(Type v3iType, int x, int y, int z)
        {
            try
            {
                foreach (var c in v3iType.GetConstructors())
                {
                    var ps = c.GetParameters();
                    if (ps.Length == 3 && ps[0].ParameterType == typeof(int))
                        return c.Invoke(new object[] { x, y, z });
                }
            }
            catch { /* fail soft */ }
            return null;
        }

        /// <summary>
        /// The one population→band ladder. CityMapLabels seed places and pack rows
        /// without a band both resolve here, and tools/realearth settlements.py
        /// Settlement.band mirrors these thresholds so a place stamps from the
        /// same prefab pool whichever side assigned its band.
        /// </summary>
        public static string BandFromPop(int pop)
        {
            if (pop >= 1_000_000) return "metro";
            if (pop >= 100_000) return "large_city";
            if (pop >= 10_000) return "town";
            if (pop >= 1_000) return "village";
            if (pop >= 100) return "hamlet";
            return "rural_scatter";
        }

        /// <summary>
        /// Soft gap 23: metro/large_city/town always pick from TraderPools when
        /// PreferTraderStamp is on (default). Other bands stay on PrefabPools hash.
        /// </summary>
        static string PickPrefab(string band, string placeName)
        {
            var cfg = ModApi.Config;
            bool preferTrader = cfg == null || cfg.PreferTraderStamp;
            if (preferTrader
                && TraderPools.TryGetValue(band, out var traders)
                && traders != null
                && traders.Length > 0)
            {
                int tIdx = unchecked((int)((uint)placeName.GetHashCode() % (uint)traders.Length));
                return traders[tIdx];
            }

            if (!PrefabPools.TryGetValue(band, out var pool) || pool.Length == 0)
                pool = PrefabPools["town"];
            int idx = unchecked((int)((uint)placeName.GetHashCode() % (uint)pool.Length));
            return pool[idx];
        }

        static bool TryPlacePrefabReflection(string prefabName, int x, int y, int z)
        {
            try
            {
                // 3.2.0: PrefabManager is gone; the prefab cache lives on the World
                // (World.m_PrefabCache, PrefabCache.GetPrefab(name, bool, bool, bool, bool)).
                // Try PrefabManager first (3.0.x), then the World field.
                object? world = ReflectCache.GetEngineWorld();
                object? pm = null;
                Type? pmType = EngineReflection.FindType("PrefabManager");
                if (pmType != null)
                    pm = pmType?.GetProperty("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null)
                        ?? pmType?.GetField("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null);

                Type? cacheType = null;
                object? cache = null;
                if (world == null)
                {
                    if (_logBudget.Allow()) ModLog.Log("RuntimePoiInject: GameManager.Instance.World null");
                }
                else
                {
                    FieldInfo? cacheField = null;
                    foreach (var f in world.GetType().GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                    {
                        if (f.Name == "m_PrefabCache") { cacheField = f; break; }
                    }
                    if (cacheField != null)
                    {
                        cache = cacheField.GetValue(world);
                        cacheType = cacheField.FieldType;
                    }
                    else
                    {
                        if (_logBudget.Allow()) ModLog.Log("RuntimePoiInject: World.m_PrefabCache field not found");
                    }
                }

                // 3.2.0 path: World.m_PrefabCache.GetPrefab(name, applyMapping, fixChildblocks, allowMissing, skipBlockData)
                if (cache != null && cacheType != null)
                {
                    MethodInfo? cacheGet = null;
                    foreach (var m in cacheType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                    {
                        if (m.Name != "GetPrefab") continue;
                        var ps = m.GetParameters();
                        if (ps.Length == 5 && ps[0].ParameterType == typeof(string))
                        {
                            cacheGet = m;
                            break;
                        }
                    }
                    if (cacheGet != null)
                    {
                        object? cachePrefab = cacheGet.Invoke(cache, new object[] { prefabName, true, true, true, false });
                        if (cachePrefab != null)
                            return PlaceResolvedPrefab(prefabName, cachePrefab, world, x, y, z);
                        if (_logBudget.Allow()) ModLog.Log($"RuntimePoiInject: PrefabCache.GetPrefab('{prefabName}') null");
                        return false;
                    }
                    if (_logBudget.Allow()) ModLog.Log($"RuntimePoiInject: no PrefabCache.GetPrefab(string,..) on {cacheType.Name}");
                    return false;
                }

                if (pmType == null)
                {
                    if (_logBudget.Allow()) ModLog.Log("RuntimePoiInject: no PrefabManager (3.0.x) and no World.m_PrefabCache (3.2.0)");
                    return false;
                }
                if (pm == null)
                {
                    if (_logBudget.Allow()) ModLog.Log("RuntimePoiInject: PrefabManager.Instance null");
                    return false;
                }

                MethodInfo? getPrefab = null;
                foreach (var m in pmType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                {
                    if (m.Name != "GetPrefab" && m.Name != "GetPrefabByName") continue;
                    var ps = m.GetParameters();
                    if (ps.Length >= 1 && ps[0].ParameterType == typeof(string))
                    {
                        getPrefab = m;
                        break;
                    }
                }
                if (getPrefab == null) { if (_logBudget.Allow()) ModLog.Log($"RuntimePoiInject: no GetPrefab method on {pmType.Name}"); return false; }
                object? prefab = getPrefab.GetParameters().Length == 1
                    ? getPrefab.Invoke(pm, new object[] { prefabName })
                    : getPrefab.Invoke(pm, new object[] { prefabName, true });
                if (prefab == null)
                {
                    if (_logBudget.Allow()) ModLog.Log($"RuntimePoiInject: GetPrefab('{prefabName}') returned null");
                    return false;
                }
                return PlaceResolvedPrefab(prefabName, prefab, ReflectCache.GetEngineWorld(), x, y, z);
            }
            catch (Exception ex)
            {
                if (_logBudget.Allow())
                    ModLog.Log($"RuntimePoiInject: prefab resolve failed '{prefabName}' ({ex.GetType().Name}: {ex.Message})");
            }
            return false;
        }

        /// <summary>
        /// Stock placement: build a PrefabInstance and call CopyIntoWorld. Verified
        /// against the V3.2.0 IL (PrefabInstance::.ctor IL=67, CopyIntoWorld IL=85)
        /// and the game's own XUiC_PrefabList call site. The old World.*Prefab*Spawn
        /// scan never matched on 3.x (all stamps ended up retry-later).
        /// </summary>
        static bool PlaceResolvedPrefab(string prefabName, object prefab, object? world, int x, int y, int z)
        {
            if (world == null) return false;
            if (TryPlaceViaPrefabInstance(prefabName, prefab, world, x, y, z, out string? piFail))
                return true;
            if (piFail != null)
                if (_logBudget.Allow()) ModLog.Log($"RuntimePoiInject: prefab path '{prefabName}' ({piFail})");
            foreach (var m in world.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (m.Name.IndexOf("Prefab", StringComparison.OrdinalIgnoreCase) < 0) continue;
                if (m.Name.IndexOf("Spawn", StringComparison.OrdinalIgnoreCase) < 0
                    && m.Name.IndexOf("Create", StringComparison.OrdinalIgnoreCase) < 0
                    && m.Name.IndexOf("Place", StringComparison.OrdinalIgnoreCase) < 0)
                    continue;
                var ps = m.GetParameters();
                if (ps.Length < 2) continue;
                try
                {
                    var args = new object?[ps.Length];
                    args[0] = prefab;
                    for (int i = 1; i < ps.Length; i++)
                    {
                        if (ps[i].ParameterType.Name.IndexOf("Vector3", StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            var vec = Activator.CreateInstance(ps[i].ParameterType);
                            if (vec != null)
                            {
                                ReflectCache.WriteComp(vec, "x", x + 0.5f);
                                ReflectCache.WriteComp(vec, "y", y);
                                ReflectCache.WriteComp(vec, "z", z + 0.5f);
                            }
                            args[i] = vec;
                        }
                        else if (ps[i].ParameterType == typeof(int))
                            args[i] = 0;
                        else if (ps[i].ParameterType == typeof(bool))
                            args[i] = false;
                        else
                            args[i] = ps[i].HasDefaultValue ? ps[i].DefaultValue : null;
                    }
                    // Do not treat arbitrary void overloads as success (burns stamp budget).
                    if (m.ReturnType == typeof(void))
                        continue;
                    object? ret = m.Invoke(world, args);
                    if (m.ReturnType == typeof(bool))
                    {
                        if (ret is true)
                            return true;
                        continue;
                    }
                    if (ret != null)
                        return true;
                }
                catch { /* try next method */ }
            }
            return false;
        }

        /// <summary>
        /// Construct a PrefabInstance(id, AbstractedLocation.None, Vector3i pos,
        /// rotation 0, prefab, standaloneBlockSize 0) and call CopyIntoWorld.
        /// Verified against the V3.2.0 IL (PrefabInstance::.ctor IL=67,
        /// CopyIntoWorld IL=85) and the game's own XUiC_PrefabList call site.
        /// </summary>
        static bool TryPlaceViaPrefabInstance(string prefabName, object prefab, object world, int x, int y, int z, out string? fail)
        {
            fail = null;
            try
            {
                Type? piType = EngineReflection.FindType("PrefabInstance");
                if (piType == null) { fail = "no PrefabInstance type"; return false; }

                ConstructorInfo? ctor = null;
                foreach (var c in piType.GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                {
                    var ps = c.GetParameters();
                    if (ps.Length == 6 && ps[4].ParameterType.Name == "Prefab")
                    {
                        ctor = c;
                        break;
                    }
                }
                if (ctor == null) { fail = "no 6-arg ctor"; return false; }

                // AbstractedLocation.None static field (or property) for the location arg.
                Type? locType = EngineReflection.FindType("AbstractedLocation");
                object? locNone = locType?.GetField("None", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null)
                    ?? locType?.GetProperty("None", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null);
                if (locNone == null) { fail = "no AbstractedLocation.None"; return false; }

                // Vector3i ctor(int, int, int)
                Type? v3i = EngineReflection.FindType("Vector3i");
                if (v3i == null) { fail = "no Vector3i type"; return false; }
                ConstructorInfo? v3iCtor = null;
                foreach (var c in v3i.GetConstructors())
                {
                    var ps = c.GetParameters();
                    if (ps.Length == 3 && ps[0].ParameterType == typeof(int)) { v3iCtor = c; break; }
                }
                if (v3iCtor == null) { fail = "no Vector3i ctor"; return false; }
                object pos = v3iCtor.Invoke(new object[] { x, y, z });

                object? instance;
                try
                {
                    instance = ctor.Invoke(new object[] { 0, locNone, pos, (byte)0, prefab, 0 });
                }
                catch (Exception ctorEx)
                {
                    fail = "ctor invoke: " + ctorEx.GetType().Name + ": " + ctorEx.Message;
                    return false;
                }
                if (instance == null) { fail = "ctor returned null"; return false; }

                MethodInfo? copy = null;
                foreach (var m in piType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                {
                    if (m.Name != "CopyIntoWorld") continue;
                    var ps = m.GetParameters();
                    if (ps.Length == 4 && ps[0].ParameterType.Name == "World")
                    {
                        copy = m;
                        break;
                    }
                }
                if (copy == null) { fail = "no CopyIntoWorld"; return false; }

                // FastTags<TagGroup/Global>.none: resolve on the CLOSED parameter
                // type (the open generic FastTags`1 throws on late-bound field
                // access), not via a named-type lookup.
                Type tagsType = copy.GetParameters()[3].ParameterType;
                object? tags = tagsType.GetField(
                    "none", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null)
                    ?? tagsType.GetField(
                    "None", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null);
                if (tags == null) { fail = "no FastTags.none"; return false; }
                copy.Invoke(instance, new object[] { world, false, true, tags });
                ModLog.Log($"RuntimePoiInject: CopyIntoWorld '{prefabName}' at ({x},{y},{z})");
                fail = null;
                return true;
            }
            catch (Exception ex)
            {
                // Visible, not silent: every retry-later stamp hides one of these.
                if (_logBudget.Allow())
                    ModLog.Log($"RuntimePoiInject: CopyIntoWorld failed '{prefabName}' ({ex.GetType().Name}: {ex.Message})");
            }
            return false;
        }
    }
}
