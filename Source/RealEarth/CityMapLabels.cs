using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using UnityEngine;

namespace RealEarth
{
    /// <summary>
    /// City names on the in-game map: discover when the player reaches the city edge,
    /// then pin the label at the geographic center (like a real map), not at the player.
    /// Similar in spirit to traders appearing when nearby; once discovered, the name stays.
    /// </summary>
    public static class CityMapLabels
    {
        static List<Place>? _catalog;
        static Dictionary<string, Place>? _catalogByName;
        static readonly HashSet<string> _discovered = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        static readonly Dictionary<string, object> _navByName = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        static int _tickThrottle;
        static int _catalogRetry = 30;
        // Reflection handles are process-stable; only the manager instance is re-read.
        static Type? _navMgrType;
        static MethodInfo? _navRegMethod;

        /// <summary>
        /// Gates all mutable label state above. TickPlayer runs on the main thread
        /// (player tick postfix) while console commands (`recities` over telnet)
        /// execute off-thread; unsynchronized HashSet/Dictionary mutation corrupts
        /// buckets, and a Reset clearing _catalog/_discovered mid-tick throws inside
        /// the discovery loops. Mirrors RuntimePoiInject._stampGate. Lock bodies stay
        /// free of other mod locks except the streamer/store locks taken by SampleY
        /// (ordering _cityGate → streamer/store; no reverse edge exists).
        /// </summary>
        static readonly object _cityGate = new object();

        public sealed class Place
        {
            public string Name = "";
            public double Lon;
            public double Lat;
            public int Population;
            public string Band = "";
            /// <summary>Discover radius in blocks (≈ m at 1:1). Edge of city.</summary>
            public int EdgeRadiusBlocks;
            /// <summary>
            /// Map-derived urban edge in meters (density blob, polygon bbox, or seed extent).
            /// 0 = not set; runtime falls back to population formula only as last resort.
            /// </summary>
            public double EdgeRadiusM;
            /// <summary>density | map | seed | population_fallback</summary>
            public string EdgeSource = "";
            /// <summary>Memoized session-local coords (invalidated on origin slide / reset).</summary>
            public bool LocalValid;
            public int CachedLocalX;
            public int CachedLocalZ;
        }

        public static int DiscoveredCount
        {
            get { lock (_cityGate) return _discovered.Count; }
        }

        public static int CatalogCount
        {
            get { lock (_cityGate) return _catalog?.Count ?? 0; }
        }

        public static void Reset()
        {
            lock (_cityGate)
            {
                UnregisterAll();
                _discovered.Clear();
                _catalog = null;
                _catalogByName = null;
                _tickThrottle = 0;
                _catalogRetry = 30;
            }
        }

        /// <summary>
        /// Session-local coords for a place, computed once and memoized on the Place.
        /// Callers must InvalidateLocalCache() when the session origin moves (slide).
        /// </summary>
        public static void LonLatToLocalCached(WorldSession session, Place p, out int cx, out int cz)
        {
            if (p.LocalValid)
            {
                cx = p.CachedLocalX;
                cz = p.CachedLocalZ;
                return;
            }
            session.LonLatToLocal(p.Lon, p.Lat, out cx, out cz);
            p.CachedLocalX = cx;
            p.CachedLocalZ = cz;
            p.LocalValid = true;
        }

        /// <summary>Drop memoized local coords after an origin change. Caller holds _cityGate.</summary>
        public static void InvalidateLocalCache()
        {
            if (_catalog == null) return;
            foreach (var p in _catalog)
                p.LocalValid = false;
        }

        /// <summary>Legacy entry: no player pos (only loads catalog / retries manager).</summary>
        public static void TryPlaceIfConfigured()
        {
            lock (_cityGate)
                EnsureCatalog();
        }

        /// <summary>
        /// Each player tick: discover cities whose edge you entered; labels always at center.
        /// force=true (console `recities here`) bypasses the shared tick throttle so the
        /// command always runs a real discovery pass instead of decrementing the counter.
        /// </summary>
        public static void TickPlayer(int playerLocalX, int playerLocalZ, bool force = false)
        {
            var cfg = ModApi.Config;
            if (cfg == null || !cfg.ShowCityNamesOnMap)
                return;

            try
            {
                lock (_cityGate)
                {
                    if (!force && _tickThrottle > 0)
                    {
                        _tickThrottle--;
                        return;
                    }
                    _tickThrottle = 15; // ~0.25s at 60fps-ish ticks; cheap distance checks

                    if (!EnsureCatalog())
                        return;
                    if (_catalog == null || _catalog.Count == 0)
                        return;

                    object? mgr = GetNavObjectManager();
                    if (mgr == null)
                        return;
                    MethodInfo? reg = ResolveRegister(mgr.GetType());
                    if (reg == null)
                        return;

                    var session = ModApi.Session;
                    if (session == null)
                        return;

                    // P6 budget: honor config but hard-cap (never ClampPrefabsInArea(cfg,cfg) identity).
                    const int hardMaxLabels = 500;
                    int maxLabels = Math.Min(Math.Max(1, cfg.CityMapMaxLabels), hardMaxLabels);
                    int minPop = Math.Max(0, cfg.CityMapMinPopulation);
                    float scale = cfg.CityMapDiscoverRadiusScale > 0.05f
                        ? cfg.CityMapDiscoverRadiusScale
                        : 1f;

                    // Re-place discovered pins if handles were dropped (e.g. origin slide).
                    // Marker position is always the city center, never the player.
                    foreach (var name in _discovered)
                    {
                        Place? p = FindByName(name);
                        if (p == null) continue;
                        if (!_navByName.ContainsKey(p.Name))
                            EnsureMarker(mgr, reg, session, p);
                    }

                    if (_discovered.Count >= maxLabels)
                        return;

                    foreach (var p in _catalog)
                    {
                        if (_discovered.Count >= maxLabels)
                            break;
                        if (p.Population < minPop && minPop > 0)
                            continue;
                        if (_discovered.Contains(p.Name))
                            continue;

                        LonLatToLocalCached(session, p, out int cx, out int cz);
                        long dx = (long)playerLocalX - cx;
                        long dz = (long)playerLocalZ - cz;
                        long distSq = dx * dx + dz * dz;
                        long edge = Math.Max(32, (int)(p.EdgeRadiusBlocks * scale));

                        // Reaching the edge is enough to discover; pin at center.
                        // Squared compare avoids a sqrt per place per window.
                        if (distSq <= edge * edge)
                        {
                            if (EnsureMarker(mgr, reg, session, p))
                            {
                                _discovered.Add(p.Name);
                                ModApi.Log(
                                    $"CityMapLabels: discovered '{p.Name}' " +
                                    $"(dist={(int)Math.Sqrt(distSq):0} edge={edge} center=({cx},{cz})).");
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                ModApi.LogWarning($"CityMapLabels tick: {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>After origin slide: keep discovered pins, recompute local positions.</summary>
        public static void RefreshAfterOriginSlide()
        {
            if (ModApi.Config == null || !ModApi.Config.ShowCityNamesOnMap)
                return;
            lock (_cityGate)
            {
                // Drop nav handles (positions invalid); rediscover set is kept.
                UnregisterAllNavOnly();
                InvalidateLocalCache();
                _tickThrottle = 0;
                // Next TickPlayer will re-place discovered at new local coords
            }
        }

        static Place? FindByName(string name) // caller holds _cityGate
        {
            if (_catalogByName != null)
                return _catalogByName.TryGetValue(name, out var hit) ? hit : null;
            if (_catalog == null) return null;
            foreach (var p in _catalog)
                if (string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase))
                    return p;
            return null;
        }

        static bool EnsureCatalog() // caller holds _cityGate
        {
            if (_catalog != null)
                return true;
            if (_catalogRetry <= 0)
                return false;
            try
            {
                var places = LoadPlaces();
                int fromMap = 0;
                foreach (var p in places)
                {
                    p.EdgeRadiusBlocks = ResolveEdgeRadiusBlocks(p);
                    if (p.EdgeSource == "density" || p.EdgeSource == "map" || p.EdgeSource == "seed")
                        fromMap++;
                }
                places.Sort((a, b) => b.Population.CompareTo(a.Population));
                _catalog = places;
                var byName = new Dictionary<string, Place>(StringComparer.OrdinalIgnoreCase);
                foreach (var p in places)
                    byName[p.Name] = p;
                _catalogByName = byName;
                ModApi.Log(
                    $"CityMapLabels: catalog {_catalog.Count} places " +
                    $"(edge from map data: {fromMap}, discover-on-approach).");
                return true;
            }
            catch (Exception ex)
            {
                _catalogRetry--;
                ModApi.LogWarning(
                    $"CityMapLabels: catalog load failed: {ex.GetType().Name}: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Prefer map-derived edge (meters → blocks at 1:1). Last resort: population formula
        /// matching the Python paint radius (sqrt(pop)/40 km, clamped).
        /// </summary>
        public static int ResolveEdgeRadiusBlocks(Place p)
        {
            // Any measured extent outranks the population formula (docs/CITY_MAP_LABELS.md
            // source priority; mirrors Python effective_edge_radius_m's > 0 test). The
            // result is still floored at 32 blocks below.
            if (p.EdgeRadiusM > 0)
            {
                if (string.IsNullOrEmpty(p.EdgeSource))
                    p.EdgeSource = "map";
                return Math.Max(32, (int)Math.Round(p.EdgeRadiusM));
            }

            // Population fallback only when pack/seed has no density or polygon extent.
            double radiusKm = Math.Max(1.5, Math.Min(80.0, Math.Sqrt(Math.Max(1, p.Population)) / 40.0));
            p.EdgeRadiusM = radiusKm * 1000.0;
            p.EdgeSource = "population_fallback";
            return Math.Max(32, (int)Math.Round(p.EdgeRadiusM));
        }

        // Band from population lives in RuntimePoiInject.BandFromPop (single ladder;
        // pack rows carry "band" so this class never needs its own copy).

        static bool EnsureMarker(
            object mgr,
            MethodInfo reg,
            WorldSession session,
            Place p)
        {
            if (_navByName.ContainsKey(p.Name))
                return true;

            // Always pin at geographic center (real map), not player position.
            LonLatToLocalCached(session, p, out int lx, out int lz);
            // P3: pin height is surface-relative (StampSurfaceY), not a magic constant only.
            int surfaceY = SampleY(lx, lz);
            int y = StampSurfaceY.PrefabRootY(surfaceY, foundationOffsetBlocks: 2);
            var pos = new Vector3(lx + 0.5f, y + 0.5f, lz + 0.5f);

            try
            {
                object? nav = reg.Invoke(mgr, new object?[]
                {
                    "realearth_city",
                    pos,
                    "",
                    false,
                    -1,
                    null
                });
                if (nav == null)
                    nav = reg.Invoke(mgr, new object?[] { "quick_waypoint", pos, "", false, -1, null });
                if (nav == null)
                    return false;

                SetNavName(nav, p.Name);
                _navByName[p.Name] = nav;
                return true;
            }
            catch (Exception ex)
            {
                ModApi.LogWarning(
                    $"CityMapLabels: pin '{p.Name}' failed: " +
                    (ex.InnerException != null
                        ? $"{ex.InnerException.GetType().Name}: {ex.InnerException.Message}"
                        : $"{ex.GetType().Name}: {ex.Message}"));
                return false;
            }
        }

        static int SampleY(int lx, int lz)
        {
            try
            {
                // Always int surface Y (never byte clamp) so tall pins sit on real peaks.
                return ChunkTerrainSampler.SampleGameHeightInt(lx, lz);
            }
            catch
            {
                return (ModApi.Config?.SeaLevelGameY ?? 100) + 20;
            }
        }

        static void SetNavName(object nav, string name)
        {
            var t = nav.GetType();
            var f = t.GetField("name", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (f != null && f.FieldType == typeof(string))
                f.SetValue(nav, name);
            var loc = t.GetField("usingLocalizationId", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (loc != null && loc.FieldType == typeof(bool))
                loc.SetValue(nav, false);
            var hidden = t.GetField("hiddenOnMap", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (hidden != null && hidden.FieldType == typeof(bool))
                hidden.SetValue(nav, false);
            var active = t.GetField("IsActive", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (active != null && active.FieldType == typeof(bool))
                active.SetValue(nav, true);
        }

        static void UnregisterAll() // caller holds _cityGate
        {
            UnregisterAllNavOnly();
            _discovered.Clear();
        }

        static void UnregisterAllNavOnly() // caller holds _cityGate
        {
            try
            {
                object? mgr = GetNavObjectManager();
                if (mgr != null)
                {
                    foreach (var kv in _navByName)
                        TryUnregister(mgr, kv.Value);
                }
            }
            catch { /* ignore */ }
            _navByName.Clear();
        }

        static void TryUnregister(object mgr, object nav)
        {
            try
            {
                foreach (var m in mgr.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                {
                    if (m.Name != "UnRegisterNavObject" || m.GetParameters().Length != 1)
                        continue;
                    m.Invoke(mgr, new[] { nav });
                    return;
                }
            }
            catch { /* ignore */ }
        }

        public static List<Place> LoadPlaces()
        {
            var list = new List<Place>();
            var paths = new List<string>();
            string mod = ModApi.ModPath ?? "";
            string pack = ModApi.Config?.TilePackPath ?? "Data/tiles";
            if (!Path.IsPathRooted(pack) && !string.IsNullOrEmpty(mod))
                pack = Path.Combine(mod, pack);

            paths.Add(Path.Combine(pack, "settlements.json"));
            paths.Add(Path.Combine(pack, "cities.json"));
            if (!string.IsNullOrEmpty(mod))
            {
                paths.Add(Path.Combine(mod, "Data", "settlements.json"));
                paths.Add(Path.Combine(mod, "Config", "settlements.json"));
            }

            foreach (var path in paths)
            {
                if (!File.Exists(path)) continue;
                try
                {
                    ParseSettlementsJson(File.ReadAllText(path), list);
                    if (list.Count > 0)
                    {
                        ModApi.Log($"CityMapLabels: loaded {list.Count} from {path}");
                        break;
                    }
                }
                catch (Exception ex)
                {
                    ModApi.LogWarning(
                        $"CityMapLabels: parse {path}: {ex.GetType().Name}: {ex.Message}");
                }
            }

            int before = list.Count;
            AddSeedPlacesInPack(list);
            if (list.Count > before)
                ModApi.Log($"CityMapLabels: +{list.Count - before} seed places in pack range");

            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var uniq = new List<Place>();
            foreach (var p in list)
            {
                if (string.IsNullOrWhiteSpace(p.Name)) continue;
                if (seen.Add(p.Name))
                    uniq.Add(p);
            }
            return uniq;
        }

        static void ParseSettlementsJson(string json, List<Place> into)
        {
            json = json.Trim();
            // cities.json is often { "cores": [ {...}, ... ] }; settlements.json is [ ... ].
            // Walk every {...} object; skip non-place objects without name+lon+lat.
            int i = 0;
            while (i < json.Length)
            {
                int objStart = json.IndexOf('{', i);
                if (objStart < 0) break;
                int objEnd = FindMatchingBrace(json, objStart);
                if (objEnd < 0) break;
                if (ContainsNestedObject(json, objStart, objEnd))
                {
                    // Container object ({ "cores": [...], "meta": {...} }): parsing it
                    // whole would yield one Frankenstein place from whichever keys
                    // appear first, and skipping to objEnd would drop every row after
                    // it. Descend so each nested place object is visited itself.
                    i = objStart + 1;
                    continue;
                }
                var place = ParsePlaceObject(json.Substring(objStart, objEnd - objStart + 1));
                if (place != null && !string.IsNullOrEmpty(place.Name))
                    into.Add(place);
                i = objEnd + 1;
            }
        }

        /// <summary>True when [start,end] spans a nested '{' outside any string literal.</summary>
        static bool ContainsNestedObject(string json, int start, int end)
        {
            bool inStr = false;
            bool esc = false;
            for (int i = start + 1; i < end; i++)
            {
                char c = json[i];
                if (inStr)
                {
                    if (esc) esc = false;
                    else if (c == '\\') esc = true;
                    else if (c == '"') inStr = false;
                    continue;
                }
                if (c == '"') inStr = true;
                else if (c == '{') return true;
            }
            return false;
        }

        static int FindMatchingBrace(string json, int openIdx)
        {
            int depth = 0;
            bool inStr = false;
            bool esc = false;
            for (int i = openIdx; i < json.Length; i++)
            {
                char c = json[i];
                if (inStr)
                {
                    if (esc) esc = false;
                    else if (c == '\\') esc = true;
                    else if (c == '"') inStr = false;
                    continue;
                }
                if (c == '"') inStr = true;
                else if (c == '{') depth++;
                else if (c == '}')
                {
                    depth--;
                    if (depth == 0) return i;
                }
            }
            return -1;
        }

        static Place? ParsePlaceObject(string obj)
        {
            var place = new Place();
            if (!TryReadString(obj, "name", out var name) || string.IsNullOrWhiteSpace(name))
                return null;
            place.Name = name;
            if (TryReadDouble(obj, "lon", out var lon)) place.Lon = lon;
            if (TryReadDouble(obj, "lat", out var lat)) place.Lat = lat;
            if (TryReadInt(obj, "population", out var pop)) place.Population = pop;
            if (TryReadString(obj, "band", out var band)) place.Band = band;
            ApplyEdgeFromObject(obj, place);
            return place;
        }

        /// <summary>
        /// Read map-data edge: edge_radius_m, radius_km, or west/south/east/north bbox.
        /// </summary>
        static void ApplyEdgeFromObject(string obj, Place place)
        {
            foreach (var key in new[] { "edge_radius_m", "radius_m", "urban_radius_m" })
            {
                if (TryReadDouble(obj, key, out var m) && m > 0)
                {
                    place.EdgeRadiusM = m;
                    // edge_source override honored only on the canonical field.
                    if (TryReadString(obj, "edge_source", out var src) && !string.IsNullOrEmpty(src))
                        place.EdgeSource = src;
                    else
                        place.EdgeSource = "map";
                    return;
                }
            }
            foreach (var key in new[] { "edge_radius_km", "radius_km" })
            {
                if (TryReadDouble(obj, key, out var km) && km > 0)
                {
                    place.EdgeRadiusM = km * 1000.0;
                    place.EdgeSource = "map";
                    return;
                }
            }
            // Real urban-area bbox → half-extent meters
            if (TryReadDouble(obj, "west", out var west)
                && TryReadDouble(obj, "south", out var south)
                && TryReadDouble(obj, "east", out var east)
                && TryReadDouble(obj, "north", out var north)
                && east > west && north > south)
            {
                place.EdgeRadiusM = EdgeMetersFromBbox(west, south, east, north, place.Lon, place.Lat);
                place.EdgeSource = "map";
            }
        }

        public static double EdgeMetersFromBbox(
            double west, double south, double east, double north,
            double centerLon, double centerLat)
        {
            if (centerLon == 0 && centerLat == 0)
            {
                centerLon = 0.5 * (west + east);
                centerLat = 0.5 * (south + north);
            }
            double mLat = 110_540.0;
            double mLon = 111_320.0 * Math.Max(0.01, Math.Abs(Math.Cos(centerLat * Math.PI / 180.0)));
            double halfW = 0.5 * Math.Abs(east - west) * mLon;
            double halfH = 0.5 * Math.Abs(north - south) * mLat;
            double corner = Math.Sqrt(
                Math.Pow((east - centerLon) * mLon, 2) +
                Math.Pow((north - centerLat) * mLat, 2));
            return Math.Max(halfW, Math.Max(halfH, corner * 0.85));
        }

        static bool TryReadString(string obj, string key, out string value)
        {
            value = "";
            string pat = "\"" + key + "\"";
            int k = obj.IndexOf(pat, StringComparison.OrdinalIgnoreCase);
            if (k < 0) return false;
            int colon = obj.IndexOf(':', k + pat.Length);
            if (colon < 0) return false;
            int q1 = obj.IndexOf('"', colon + 1);
            if (q1 < 0) return false;
            // Scan to the real closing quote (skipping \\-escaped ones), then
            // decode JSON escapes: place names may be stored as \uXXXX sequences.
            int q2 = -1;
            bool esc = false;
            for (int i = q1 + 1; i < obj.Length; i++)
            {
                char c = obj[i];
                if (esc) { esc = false; continue; }
                if (c == '\\') { esc = true; continue; }
                if (c == '"') { q2 = i; break; }
            }
            if (q2 < 0) return false;
            value = UnescapeJson(obj.Substring(q1 + 1, q2 - q1 - 1));
            return true;
        }

        /// <summary>
        /// Decode JSON string escapes (\uXXXX incl. surrogate halves, \b \f \n \r \t,
        /// \" \\ \/). Invalid escapes pass through unchanged rather than throwing.
        /// </summary>
        static string UnescapeJson(string s)
        {
            if (s.IndexOf('\\') < 0)
                return s;
            var sb = new System.Text.StringBuilder(s.Length);
            int i = 0;
            while (i < s.Length)
            {
                char c = s[i];
                if (c != '\\' || i + 1 >= s.Length)
                {
                    sb.Append(c);
                    i++;
                    continue;
                }
                char n = s[i + 1];
                switch (n)
                {
                    case '"': sb.Append('"'); i += 2; break;
                    case '\\': sb.Append('\\'); i += 2; break;
                    case '/': sb.Append('/'); i += 2; break;
                    case 'b': sb.Append('\b'); i += 2; break;
                    case 'f': sb.Append('\f'); i += 2; break;
                    case 'n': sb.Append('\n'); i += 2; break;
                    case 'r': sb.Append('\r'); i += 2; break;
                    case 't': sb.Append('\t'); i += 2; break;
                    case 'u':
                        if (i + 6 <= s.Length && TryHex4(s, i + 2, out char u))
                        {
                            sb.Append(u);
                            i += 6;
                        }
                        else
                        {
                            sb.Append(c);
                            i++;
                        }
                        break;
                    default:
                        sb.Append(c);
                        i++;
                        break;
                }
            }
            return sb.ToString();
        }

        static bool TryHex4(string s, int start, out char value)
        {
            value = '\0';
            if (start + 4 > s.Length) return false;
            int v = 0;
            for (int i = start; i < start + 4; i++)
            {
                char ch = s[i];
                int digit = ch >= '0' && ch <= '9' ? ch - '0'
                    : ch >= 'a' && ch <= 'f' ? ch - 'a' + 10
                    : ch >= 'A' && ch <= 'F' ? ch - 'A' + 10
                    : -1;
                if (digit < 0) return false;
                v = (v << 4) | digit;
            }
            value = (char)v;
            return true;
        }

        static bool TryReadDouble(string obj, string key, out double value)
        {
            value = 0;
            string pat = "\"" + key + "\"";
            int k = obj.IndexOf(pat, StringComparison.OrdinalIgnoreCase);
            if (k < 0) return false;
            int colon = obj.IndexOf(':', k + pat.Length);
            if (colon < 0) return false;
            int j = colon + 1;
            while (j < obj.Length && (obj[j] == ' ' || obj[j] == '\t')) j++;
            int e = j;
            while (e < obj.Length && (char.IsDigit(obj[e]) || obj[e] == '-' || obj[e] == '+' || obj[e] == '.' || obj[e] == 'e' || obj[e] == 'E'))
                e++;
            return double.TryParse(obj.Substring(j, e - j), NumberStyles.Float, CultureInfo.InvariantCulture, out value);
        }

        static bool TryReadInt(string obj, string key, out int value)
        {
            value = 0;
            if (!TryReadDouble(obj, key, out double d)) return false;
            value = (int)d;
            return true;
        }

        static void AddSeedPlacesInPack(List<Place> into)
        {
            // edge_m ≈ real urban continuum half-width (map extent order-of-magnitude).
            var seeds = new (string n, double lon, double lat, int pop, string band, double edgeM)[]
            {
                ("New York", -74.006, 40.7128, 8_300_000, "metro", 35_000),
                ("Los Angeles", -118.2437, 34.0522, 3_900_000, "metro", 45_000),
                ("Chicago", -87.6298, 41.8781, 2_700_000, "metro", 28_000),
                ("Denver", -104.9903, 39.7392, 715_000, "large_city", 22_000),
                ("London", -0.1276, 51.5074, 9_000_000, "metro", 28_000),
                ("Paris", 2.3522, 48.8566, 2_100_000, "metro", 18_000),
                ("Berlin", 13.4050, 52.5200, 3_700_000, "metro", 16_000),
                ("Tokyo", 139.6917, 35.6895, 14_000_000, "metro", 40_000),
                ("Sydney", 151.2093, -33.8688, 5_300_000, "metro", 22_000),
                ("São Paulo", -46.6333, -23.5505, 12_500_000, "metro", 30_000),
                ("Cairo", 31.2357, 30.0444, 10_000_000, "metro", 22_000),
                ("Mumbai", 72.8777, 19.0760, 12_500_000, "metro", 25_000),
                ("Kathmandu", 85.3240, 27.7172, 1_400_000, "large_city", 10_000),
                ("Namche Bazaar", 86.7140, 27.8069, 1_600, "village", 800),
                ("Lukla", 86.7314, 27.6866, 1_500, "village", 600),
                ("Dingboche", 86.8360, 27.8920, 200, "hamlet", 400),
                ("Base Camp", 86.8525, 28.0026, 50, "hamlet", 300),
            };

            var cfg = ModApi.Config;
            bool hasBbox = cfg != null && cfg.HasRegionalBbox;
            foreach (var s in seeds)
            {
                if (hasBbox)
                {
                    if (s.lon < cfg!.BboxWest || s.lon > cfg.BboxEast) continue;
                    if (s.lat < cfg.BboxSouth || s.lat > cfg.BboxNorth) continue;
                }
                into.Add(new Place
                {
                    Name = s.n,
                    Lon = s.lon,
                    Lat = s.lat,
                    Population = s.pop,
                    Band = s.band,
                    EdgeRadiusM = s.edgeM,
                    EdgeSource = "seed",
                });
            }
        }

        static object? GetNavObjectManager()
        {
            try
            {
                if (_navMgrType == null)
                    _navMgrType = EngineReflection.FindType("NavObjectManager");
                var t = _navMgrType;
                if (t == null) return null;
                var f = t.GetField("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
                        ?? t.GetField("instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                var p = t.GetProperty("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                return f?.GetValue(null) ?? p?.GetValue(null, null);
            }
            catch
            {
                return null;
            }
        }

        /// <summary>RegisterNavObject MethodInfo resolved once per manager type (per-window scan otherwise).</summary>
        static MethodInfo? ResolveRegister(Type mgrType)
        {
            if (_navRegMethod != null && _navRegMethod.DeclaringType == mgrType)
                return _navRegMethod;
            _navRegMethod = FindRegister(mgrType);
            return _navRegMethod;
        }

        static MethodInfo? FindRegister(Type mgrType)
        {
            foreach (var m in mgrType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (m.Name != "RegisterNavObject") continue;
                var ps = m.GetParameters();
                if (ps.Length == 6
                    && ps[0].ParameterType == typeof(string)
                    && ps[1].ParameterType.Name == "Vector3"
                    && ps[2].ParameterType == typeof(string))
                    return m;
            }
            foreach (var m in mgrType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (m.Name != "RegisterNavObject") continue;
                var ps = m.GetParameters();
                if (ps.Length >= 2 && ps[0].ParameterType == typeof(string) && ps[1].ParameterType.Name == "Vector3")
                    return m;
            }
            return null;
        }
    }
}
