using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace RealEarth
{
    /// <summary>
    /// P4: absolute session snapshot for save/reload (origin + absolute Earth + MP mode).
    /// Minimal JSON without external deps (offline-testable).
    /// </summary>
    public sealed class SessionSnapshot
    {
        public int OriginEarthX;
        public int OriginEarthZ;
        public int AbsoluteX;
        public int AbsoluteZ;
        public string MapMode = "Streamed";
        public string MultiplayerOriginMode = "SoloSlide";
        public double SpawnLon;
        public double SpawnLat;
        /// <summary>
        /// Hashed world-save identity ("" = unknown / legacy snapshot). Restore skips
        /// snapshots from a different scope so a new world never inherits another
        /// world's absolute position through the global mod Config fallback file.
        /// </summary>
        public string Scope = "";

        /// <summary>
        /// Soft gap 32: city names discovered this world (session-scoped). Empty when
        /// none or legacy snapshots. Names are catalog keys; markers re-place on tick.
        /// </summary>
        public List<string> DiscoveredCities = new List<string>();

        public string ToJson()
        {
            var sb = new StringBuilder(256);
            sb.Append('{');
            sb.Append("\"schema\":\"realearth.session.v1\",");
            sb.Append("\"originEarthX\":").Append(OriginEarthX).Append(',');
            sb.Append("\"originEarthZ\":").Append(OriginEarthZ).Append(',');
            sb.Append("\"absoluteX\":").Append(AbsoluteX).Append(',');
            sb.Append("\"absoluteZ\":").Append(AbsoluteZ).Append(',');
            sb.Append("\"mapMode\":\"").Append(Escape(MapMode)).Append("\",");
            sb.Append("\"multiplayerOriginMode\":\"").Append(Escape(MultiplayerOriginMode)).Append("\",");
            sb.Append("\"spawnLon\":").Append(SpawnLon.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"spawnLat\":").Append(SpawnLat.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"scope\":\"").Append(Escape(Scope)).Append('"');
            if (DiscoveredCities != null && DiscoveredCities.Count > 0)
            {
                sb.Append(",\"discoveredCities\":[");
                for (int i = 0; i < DiscoveredCities.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append('"').Append(Escape(DiscoveredCities[i] ?? "")).Append('"');
                }
                sb.Append(']');
            }
            sb.Append('}');
            return sb.ToString();
        }

        public static bool TryParse(string json, out SessionSnapshot snap)
        {
            snap = new SessionSnapshot();
            if (string.IsNullOrWhiteSpace(json)) return false;
            try
            {
                if (!TryReadInt(json, "originEarthX", out snap.OriginEarthX)) return false;
                if (!TryReadInt(json, "originEarthZ", out snap.OriginEarthZ)) return false;
                if (!TryReadInt(json, "absoluteX", out snap.AbsoluteX)) return false;
                if (!TryReadInt(json, "absoluteZ", out snap.AbsoluteZ)) return false;
                // Optional strings: do not blank defaults on missing keys.
                if (TryReadString(json, "mapMode", out var mm) && !string.IsNullOrEmpty(mm))
                    snap.MapMode = mm;
                if (TryReadString(json, "multiplayerOriginMode", out var mom) && !string.IsNullOrEmpty(mom))
                    snap.MultiplayerOriginMode = mom;
                // Optional scope (legacy snapshots have none = apply anywhere).
                if (TryReadString(json, "scope", out var sc))
                    snap.Scope = sc ?? "";
                if (TryReadDouble(json, "spawnLon", out var slon))
                    snap.SpawnLon = slon;
                if (TryReadDouble(json, "spawnLat", out var slat))
                    snap.SpawnLat = slat;
                // Optional; legacy snapshots omit the key.
                if (TryReadStringArray(json, "discoveredCities", out var cities))
                    snap.DiscoveredCities = cities;
                return true;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Hashed identity of the current world save ("" when unavailable, e.g. offline).
        /// A path hash rather than the raw path: session files may be shared, and the
        /// comparison only needs equality.
        /// </summary>
        public static string ScopeForCurrentWorld()
        {
            string? id = WorldSavePath.SessionScopeId();
            if (string.IsNullOrEmpty(id)) return "";
            unchecked
            {
                ulong h = 14695981039346656037UL;
                foreach (char c in id!)
                {
                    h ^= c;
                    h *= 1099511628211UL;
                }
                return h.ToString("x16", CultureInfo.InvariantCulture);
            }
        }

        /// <summary>
        /// JSON string body: quote, backslash, and every C0/C1 control char escaped.
        /// Control chars matter because the reader below scans for a closing quote
        /// that respects backslash escapes: a raw CR inside a value would end the
        /// line the way an operator reads the file. Non-ASCII is written as UTF-8
        /// rather than \uXXXX; the file is declared UTF-8 and read as such.
        /// </summary>
        static string Escape(string s)
        {
            s = s ?? "";
            if (s.IndexOfAny(EscapeChars) < 0) return s;
            var sb = new StringBuilder(s.Length + 8);
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < ' ' || (c >= '\u007f' && c <= '\u009f'))
                            sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        else
                            sb.Append(c);
                        break;
                }
            }
            return sb.ToString();
        }

        static readonly char[] EscapeChars = { '"', '\\', '\b', '\f', '\n', '\r', '\t', '\u007f' };

        /// <summary>
        /// Index of the closing quote of the string opened at `open`, skipping
        /// backslash-escaped quotes, or -1 when unterminated. A plain
        /// IndexOf('"') stops at the \" of a value like `Foo\"Bar`, so the reader
        /// returned a truncated name that no longer matches the catalog key.
        /// </summary>
        static int FindStringEnd(string json, int open)
        {
            bool esc = false;
            for (int i = open + 1; i < json.Length; i++)
            {
                char c = json[i];
                if (esc) { esc = false; continue; }
                if (c == '\\') { esc = true; continue; }
                if (c == '"') return i;
            }
            return -1;
        }

        /// <summary>Inverse of Escape for the escapes it emits.</summary>
        static string Unescape(string s)
        {
            if (s.IndexOf('\\') < 0) return s;
            var sb = new StringBuilder(s.Length);
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                if (c != '\\' || i + 1 >= s.Length) { sb.Append(c); continue; }
                char n = s[++i];
                switch (n)
                {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (i + 4 < s.Length
                            && ushort.TryParse(s.Substring(i + 1, 4), NumberStyles.HexNumber,
                                CultureInfo.InvariantCulture, out ushort u))
                        {
                            sb.Append((char)u);
                            i += 4;
                        }
                        else
                        {
                            sb.Append(c);
                            i--;
                        }
                        break;
                    default: sb.Append(c); break;
                }
            }
            return sb.ToString();
        }

        /// <summary>Index just past the colon of `"key":`, or -1 when absent.</summary>
        static int KeyColonIndex(string json, string key)
        {
            string pat = "\"" + key + "\"";
            int k = json.IndexOf(pat, StringComparison.OrdinalIgnoreCase);
            if (k < 0) return -1;
            int colon = json.IndexOf(':', k + pat.Length);
            return colon < 0 ? -1 : colon + 1;
        }

        static bool TryReadInt(string json, string key, out int value)
        {
            value = 0;
            int j = KeyColonIndex(json, key);
            if (j < 0) return false;
            while (j < json.Length && (json[j] == ' ' || json[j] == '\t')) j++;
            int e = j;
            while (e < json.Length && (char.IsDigit(json[e]) || json[e] == '-')) e++;
            return int.TryParse(json.Substring(j, e - j), NumberStyles.Integer, CultureInfo.InvariantCulture, out value);
        }

        static bool TryReadDouble(string json, string key, out double value)
        {
            value = 0;
            int j = KeyColonIndex(json, key);
            if (j < 0) return false;
            while (j < json.Length && (json[j] == ' ' || json[j] == '\t')) j++;
            int e = j;
            while (e < json.Length && (char.IsDigit(json[e]) || json[e] == '-' || json[e] == '+' || json[e] == '.' || json[e] == 'e' || json[e] == 'E'))
                e++;
            return double.TryParse(json.Substring(j, e - j), NumberStyles.Float, CultureInfo.InvariantCulture, out value);
        }

        static bool TryReadString(string json, string key, out string value)
        {
            value = "";
            int j = KeyColonIndex(json, key);
            if (j < 0) return false;
            int q1 = json.IndexOf('"', j);
            if (q1 < 0) return false;
            int q2 = FindStringEnd(json, q1);
            if (q2 < 0) return false;
            value = Unescape(json.Substring(q1 + 1, q2 - q1 - 1));
            return true;
        }

        /// <summary>Optional string array; returns false when key absent.</summary>
        static bool TryReadStringArray(string json, string key, out List<string> values)
        {
            values = new List<string>();
            int j = KeyColonIndex(json, key);
            if (j < 0) return false;
            while (j < json.Length && (json[j] == ' ' || json[j] == '\t')) j++;
            if (j >= json.Length || json[j] != '[') return false;
            j++;
            while (j < json.Length)
            {
                while (j < json.Length && (json[j] == ' ' || json[j] == '\t' || json[j] == ',' || json[j] == '\n' || json[j] == '\r'))
                    j++;
                if (j >= json.Length) return false;
                if (json[j] == ']') return true;
                if (json[j] != '"') return false;
                int q1 = j;
                int q2 = FindStringEnd(json, q1);
                if (q2 < 0) return false;
                string s = Unescape(json.Substring(q1 + 1, q2 - q1 - 1));
                if (s.Length > 0)
                    values.Add(s);
                j = q2 + 1;
            }
            return false;
        }
    }

    public static class SessionStateStore
    {
        public static string DefaultSessionPath()
        {
            string mod = ModApi.ModPath ?? ".";
            return Path.Combine(mod, "Config", "realearth.session.json");
        }

        /// <summary>Primary path: stock save dir when available, else mod Config.</summary>
        public static string PreferredSessionPath() => WorldSavePath.SessionPath();

        public static SessionSnapshot Capture(WorldSession session, RealEarthConfig? cfg)
        {
            double lon = 0, lat = 0;
            try
            {
                session.EarthToLonLat(session.AbsoluteX, session.AbsoluteZ, out lon, out lat);
            }
            catch
            {
                lon = cfg?.DefaultSpawnLon ?? 0;
                lat = cfg?.DefaultSpawnLat ?? 0;
            }
            return new SessionSnapshot
            {
                OriginEarthX = session.OriginEarthX,
                OriginEarthZ = session.OriginEarthZ,
                AbsoluteX = session.AbsoluteX,
                AbsoluteZ = session.AbsoluteZ,
                MapMode = cfg?.MapMode ?? "Streamed",
                MultiplayerOriginMode = cfg?.MultiplayerOriginMode ?? "SoloSlide",
                SpawnLon = lon,
                SpawnLat = lat,
                Scope = SessionSnapshot.ScopeForCurrentWorld(),
                DiscoveredCities = CityMapLabels.ExportDiscoveredNames(),
            };
        }

        /// <summary>
        /// Restore exact origin + absolute Earth. Does not recenter (preserves saved origin).
        /// </summary>
        public static bool TryApply(WorldSession session, SessionSnapshot snap)
        {
            if (session == null || snap == null) return false;
            session.RestoreSnapshot(
                snap.OriginEarthX, snap.OriginEarthZ,
                snap.AbsoluteX, snap.AbsoluteZ);
            return true;
        }

        /// <summary>
        /// Paths to try in order: explicit operator override, else stock save dir
        /// primary + mod Config fallback (deduped case-insensitively).
        /// </summary>
        static List<string> SessionCandidatePaths(string? path)
        {
            var paths = new List<string>();
            if (!string.IsNullOrEmpty(path))
            {
                paths.Add(path!);
            }
            else
            {
                paths.Add(PreferredSessionPath());
                string fallback = DefaultSessionPath();
                if (!string.Equals(paths[0], fallback, StringComparison.OrdinalIgnoreCase))
                    paths.Add(fallback);
            }
            return paths;
        }

        public static bool TrySave(WorldSession session, RealEarthConfig? cfg, string? path = null)
        {
            try
            {
                var snap = Capture(session, cfg);
                string json = snap.ToJson() + "\n";
                // Dual-write: stock world save dir (primary) + mod Config fallback.
                bool any = false;
                foreach (var p in SessionCandidatePaths(path))
                {
                    try
                    {
                        string? dir = Path.GetDirectoryName(p);
                        if (!string.IsNullOrEmpty(dir))
                            Directory.CreateDirectory(dir!);
                        AtomicPublish.WriteAllText(p, json);
                        any = true;
                    }
                    catch (Exception ex)
                    {
                        ModApi.LogWarn("SessionStateStore.TrySave path " + p, ex);
                    }
                }
                return any;
            }
            catch (Exception ex)
            {
                ModApi.LogError("SessionStateStore.TrySave", ex);
                return false;
            }
        }

        public static bool TryLoad(WorldSession session, string? path = null)
        {
            try
            {
                // Explicit path is an operator override: no scope gate.
                bool explicitPath = !string.IsNullOrEmpty(path);
                string currentScope = explicitPath ? "" : SessionSnapshot.ScopeForCurrentWorld();
                foreach (var p in SessionCandidatePaths(path))
                {
                    if (!File.Exists(p)) continue;
                    // Per-path isolation, matching TrySave: an unreadable or
                    // corrupt primary must not skip the fallback snapshot.
                    string json;
                    SessionSnapshot snap;
                    try
                    {
                        json = File.ReadAllText(p, Encoding.UTF8);
                    }
                    catch (Exception ex)
                    {
                        ModApi.LogWarn("SessionStateStore read failed " + p + ": " + ex.GetType().Name + ": " + ex.Message);
                        continue;
                    }
                    if (!SessionSnapshot.TryParse(json, out snap))
                    {
                        // Skipping a snapshot silently reads as "no session": the world
                        // restarts at the config spawn and the operator only finds out
                        // by noticing the origin moved. Name the file and its size.
                        ModApi.LogWarn(
                            $"SessionStateStore skip unreadable snapshot {p} bytes={Encoding.UTF8.GetByteCount(json)}");
                        continue;
                    }
                    // The mod Config fallback is global across worlds; without this gate a
                    // new world would restore the previous world's absolute position
                    // (spawn far from the intended config spawn). Unknown scopes on either
                    // side apply as before (legacy snapshots, offline contexts).
                    if (snap.Scope.Length > 0 && currentScope.Length > 0
                        && !string.Equals(snap.Scope, currentScope, StringComparison.Ordinal))
                    {
                        ModApi.Log("SessionStateStore skip " + p + " (different world scope)");
                        continue;
                    }
                    if (TryApply(session, snap))
                    {
                        // Soft gap 32: re-seed city discoveries (markers re-place on tick).
                        int n = CityMapLabels.RestoreDiscoveredNames(snap.DiscoveredCities);
                        if (n > 0)
                            ModApi.Log("SessionStateStore restored " + n + " discovered cities");
                        ModApi.Log("SessionStateStore loaded from " + p);
                        return true;
                    }
                }
                return false;
            }
            catch (Exception ex)
            {
                ModApi.LogError("SessionStateStore.TryLoad", ex);
                return false;
            }
        }

    }
}
