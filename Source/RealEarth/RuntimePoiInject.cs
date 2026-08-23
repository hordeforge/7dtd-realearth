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
        static readonly Dictionary<string, string[]> PrefabPools = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
        {
            ["metro"] = new[] { "downtown_building_04", "commercial_strip_08", "gas_station_05", "house_modern_15" },
            ["large_city"] = new[] { "downtown_strip_06", "commercial_site_02", "gas_station_03", "house_modern_10" },
            ["town"] = new[] { "commercial_strip_10", "gas_station_01", "house_modern_05", "church_01" },
            ["village"] = new[] { "gas_station_01", "house_country_01", "cabin_01", "farm_11" },
            ["hamlet"] = new[] { "cabin_02", "house_old_cottage_01", "barn_01", "abandoned_house_01" },
            ["rural_scatter"] = new[] { "cabin_06", "farm_19", "abandoned_house_03" },
        };

        const int MaxPlaceFails = 5;

        /// <summary>
        /// Gates all mutable stamp state below. TickPlayer runs on the main thread while
        /// OnChunkGenerated runs on the chunk-generation thread; unsynchronized
        /// HashSet/Dictionary mutation corrupts buckets, and unlocked budget checks lose
        /// updates (double stamps or stranded budget). Reset/OnOriginSlide clear these
        /// collections from the main thread, so they take the same gate.
        /// </summary>
        static readonly object _stampGate = new object();

        static int _tickThrottle;
        static int _logBudget = 12;
        static int _sessionStamps;
        static List<CityMapLabels.Place>? _placesCache;
        static readonly Dictionary<string, int> _chunkCounts = new Dictionary<string, int>(StringComparer.Ordinal);

        public static int SessionStampCount => Volatile.Read(ref _sessionStamps);

        /// <summary>Consume one log-budget slot (shared across threads; see _stampGate).</summary>
        static bool ConsumeLogBudget() => Interlocked.Decrement(ref _logBudget) >= 0;

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
                Volatile.Write(ref _logBudget, 12);
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

        /// <summary>Player tick: stamp nearby city cores under DensityBudget.</summary>
        public static void TickPlayer(int playerLocalX, int playerLocalZ)
        {
            var cfg = ModApi.Config;
            if (cfg == null || !cfg.EnableRuntimePoiInject)
                return;
            if (_tickThrottle > 0)
            {
                _tickThrottle--;
                return;
            }
            _tickThrottle = 40;

            try
            {
                lock (_stampGate)
                {
                    var session = ModApi.Session;
                    if (session == null) return;
                    if (_placesCache == null)
                        _placesCache = CityMapLabels.LoadPlaces();
                    if (_placesCache == null || _placesCache.Count == 0) return;

                    int maxArea = DensityBudget.ClampPrefabsInArea(
                        Math.Max(1, cfg.RuntimePoiMaxPerArea),
                        DensityBudget.DefaultMaxPrefabsPerKm2);
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
                        double edge = Math.Max(32, (int)(CityMapLabels.ResolveEdgeRadiusBlocks(p) * discoverScale));
                        double reach = edge * 1.5;
                        if (distSq > reach * reach)
                            continue;

                        string chunkKey = FloorDiv(cx, 16).ToString(CultureInfo.InvariantCulture) + ":" +
                                          FloorDiv(cz, 16).ToString(CultureInfo.InvariantCulture);
                        StampWithBudget(session, p, cx, cz, chunkKey);
                    }
                }
            }
            catch (Exception ex)
            {
                if (ConsumeLogBudget())
                {
                    ModApi.Log("RuntimePoiInject: " + ex.Message);
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

                    int maxArea = DensityBudget.ClampPrefabsInArea(
                        Math.Max(1, cfg.RuntimePoiMaxPerArea),
                        DensityBudget.DefaultMaxPrefabsPerKm2);
                    if (_sessionStamps >= maxArea) return;

                    int minX = chunkX * 16;
                    int minZ = chunkZ * 16;
                    int maxX = minX + 16;
                    int maxZ = minZ + 16;
                    string chunkKey = chunkX.ToString(CultureInfo.InvariantCulture) + ":" +
                                      chunkZ.ToString(CultureInfo.InvariantCulture);

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
                if (ConsumeLogBudget())
                {
                    ModApi.Log("RuntimePoiInject chunk: " + ex.Message);
                }
            }
        }

        /// <summary>
        /// Shared stamp tail for TickPlayer / OnChunkGenerated (caller holds _stampGate):
        /// chunk-budget gate, place attempt, and success/fail accounting.
        /// </summary>
        static void StampWithBudget(WorldSession session, CityMapLabels.Place p, int cx, int cz, string chunkKey)
        {
            int inChunk = _chunkCounts.TryGetValue(chunkKey, out int c) ? c : 0;
            if (DensityBudget.ClampPrefabsInChunk(inChunk + 1) <= inChunk)
                return;
            if (TryStampPlace(session, p, cx, cz))
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

        static bool TryStampPlace(WorldSession session, CityMapLabels.Place p, int localX, int localZ)
        {
            int surface = ChunkTerrainSampler.SampleGameHeightInt(localX, localZ);
            int y = StampSurfaceY.PrefabRootY(surface, foundationOffsetBlocks: 0);
            string band = string.IsNullOrEmpty(p.Band) ? BandFromPop(p.Population) : p.Band;
            if (!PrefabPools.TryGetValue(band, out var pool) || pool.Length == 0)
                pool = PrefabPools["town"];
            int idx = unchecked((int)((uint)p.Name.GetHashCode() % (uint)pool.Length));
            string prefabName = pool[idx];

            bool placed = TryPlacePrefabReflection(prefabName, localX, y, localZ);
            if (ConsumeLogBudget())
            {
                ModApi.Log(
                    $"RuntimePoiInject: {(placed ? "placed" : "retry-later")} '{prefabName}' " +
                    $"for '{p.Name}' band={band} local=({localX},{y},{localZ}) surface={surface}");
            }
            return placed;
        }

        static string BandFromPop(int pop)
        {
            if (pop >= 1_000_000) return "metro";
            if (pop >= 100_000) return "large_city";
            if (pop >= 10_000) return "town";
            if (pop >= 1_000) return "village";
            if (pop >= 100) return "hamlet";
            return "rural_scatter";
        }

        static bool TryPlacePrefabReflection(string prefabName, int x, int y, int z)
        {
            try
            {
                Type? pmType = FindType("PrefabManager");
                object? pm = pmType?.GetProperty("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null)
                    ?? pmType?.GetField("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null);
                if (pm == null || pmType == null) return false;

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
                if (getPrefab == null) return false;
                object? prefab = getPrefab.GetParameters().Length == 1
                    ? getPrefab.Invoke(pm, new object[] { prefabName })
                    : getPrefab.Invoke(pm, new object[] { prefabName, true });
                if (prefab == null) return false;

                object? world = ReflectCache.GetEngineWorld();
                if (world == null) return false;
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
            }
            catch { /* ignore */ }
            return false;
        }

        static int FloorDiv(int a, int b)
        {
            if (b == 0) return 0;
            if (a >= 0) return a / b;
            return (a - (b - 1)) / b;
        }

        static Type? FindType(string name)
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    foreach (var ty in asm.GetTypes())
                        if (ty.Name == name) return ty;
                }
                catch (ReflectionTypeLoadException ex)
                {
                    foreach (var ty in ex.Types ?? Array.Empty<Type>())
                        if (ty != null && ty.Name == name) return ty;
                }
                catch { /* ignore */ }
            }
            return null;
        }
    }
}
