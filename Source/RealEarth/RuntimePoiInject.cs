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
                Volatile.Write(ref _logBudget, 24);
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

                        string chunkKey = EngineReflection.FloorDiv(cx, 16).ToString(CultureInfo.InvariantCulture) + ":" +
                                          EngineReflection.FloorDiv(cz, 16).ToString(CultureInfo.InvariantCulture);
                        StampWithBudget(session, p, cx, cz, chunkKey);
                    }
                }
            }
            catch (Exception ex)
            {
                if (ConsumeLogBudget())
                {
                    ModApi.LogError("RuntimePoiInject: " + ex.GetType().Name + ": " + ex.Message);
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
                    ModApi.LogError("RuntimePoiInject chunk: " + ex.GetType().Name + ": " + ex.Message);
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
                    if (ConsumeLogBudget()) ModApi.Log("RuntimePoiInject: GameManager.Instance.World null");
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
                        if (ConsumeLogBudget()) ModApi.Log("RuntimePoiInject: World.m_PrefabCache field not found");
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
                        if (ConsumeLogBudget()) ModApi.Log($"RuntimePoiInject: PrefabCache.GetPrefab('{prefabName}') null");
                        return false;
                    }
                    if (ConsumeLogBudget()) ModApi.Log($"RuntimePoiInject: no PrefabCache.GetPrefab(string,..) on {cacheType.Name}");
                    return false;
                }

                if (pmType == null)
                {
                    if (ConsumeLogBudget()) ModApi.Log("RuntimePoiInject: no PrefabManager (3.0.x) and no World.m_PrefabCache (3.2.0)");
                    return false;
                }
                if (pm == null)
                {
                    if (ConsumeLogBudget()) ModApi.Log("RuntimePoiInject: PrefabManager.Instance null");
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
                if (getPrefab == null) { if (ConsumeLogBudget()) ModApi.Log($"RuntimePoiInject: no GetPrefab method on {pmType.Name}"); return false; }
                object? prefab = getPrefab.GetParameters().Length == 1
                    ? getPrefab.Invoke(pm, new object[] { prefabName })
                    : getPrefab.Invoke(pm, new object[] { prefabName, true });
                if (prefab == null)
                {
                    if (ConsumeLogBudget()) ModApi.Log($"RuntimePoiInject: GetPrefab('{prefabName}') returned null");
                    return false;
                }
                return PlaceResolvedPrefab(prefabName, prefab, ReflectCache.GetEngineWorld(), x, y, z);
            }
            catch (Exception ex)
            {
                if (ConsumeLogBudget())
                    ModApi.Log($"RuntimePoiInject: prefab resolve failed '{prefabName}' ({ex.GetType().Name}: {ex.Message})");
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
                if (ConsumeLogBudget()) ModApi.Log($"RuntimePoiInject: prefab path '{prefabName}' ({piFail})");
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
                ModApi.Log($"RuntimePoiInject: CopyIntoWorld '{prefabName}' at ({x},{y},{z})");
                fail = null;
                return true;
            }
            catch (Exception ex)
            {
                // Visible, not silent: every retry-later stamp hides one of these.
                if (ConsumeLogBudget())
                    ModApi.Log($"RuntimePoiInject: CopyIntoWorld failed '{prefabName}' ({ex.GetType().Name}: {ex.Message})");
            }
            return false;
        }
    }
}
