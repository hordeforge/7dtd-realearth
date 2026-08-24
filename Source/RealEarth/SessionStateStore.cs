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

        static string Escape(string s) =>
            (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");

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
            int q2 = json.IndexOf('"', q1 + 1);
            if (q2 < 0) return false;
            value = json.Substring(q1 + 1, q2 - q1 - 1);
            return true;
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
                        WriteTextAtomic(p, json);
                        any = true;
                    }
                    catch (Exception ex)
                    {
                        ModApi.Log("SessionStateStore.TrySave path " + p + ": " + ex.Message);
                    }
                }
                return any;
            }
            catch (Exception ex)
            {
                ModApi.Log("SessionStateStore.TrySave: " + ex.Message);
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
                    string json = File.ReadAllText(p);
                    if (!SessionSnapshot.TryParse(json, out var snap)) continue;
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
                        ModApi.Log("SessionStateStore loaded from " + p);
                        return true;
                    }
                }
                return false;
            }
            catch (Exception ex)
            {
                ModApi.Log("SessionStateStore.TryLoad: " + ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Atomic-ish write: unique temp + Replace so a crash mid-save can never leave a
        /// truncated session file (which would silently reset spawn to config defaults).
        /// </summary>
        static void WriteTextAtomic(string path, string contents)
        {
            string tmp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(tmp, contents);
            }
            catch
            {
                TryDeleteQuiet(tmp);
                throw;
            }
            try
            {
                if (File.Exists(path))
                    File.Replace(tmp, path, null);
                else
                    File.Move(tmp, path);
            }
            catch
            {
                TryDeleteQuiet(tmp);
                throw;
            }
        }

        static void TryDeleteQuiet(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); }
            catch { /* best effort */ }
        }
    }
}
