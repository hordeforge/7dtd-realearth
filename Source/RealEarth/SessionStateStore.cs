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
            sb.Append("\"spawnLat\":").Append(SpawnLat.ToString(CultureInfo.InvariantCulture));
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

        /// <summary>P4 player-build delta key for a tile (absolute Earth tile indices).</summary>
        public static string DeltaKey(int tileX, int tileZ) =>
            tileX.ToString(CultureInfo.InvariantCulture) + ":" + tileZ.ToString(CultureInfo.InvariantCulture);

        static string Escape(string s) =>
            (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");

        static bool TryReadInt(string json, string key, out int value)
        {
            value = 0;
            string pat = "\"" + key + "\"";
            int k = json.IndexOf(pat, StringComparison.OrdinalIgnoreCase);
            if (k < 0) return false;
            int colon = json.IndexOf(':', k + pat.Length);
            if (colon < 0) return false;
            int j = colon + 1;
            while (j < json.Length && (json[j] == ' ' || json[j] == '\t')) j++;
            int e = j;
            while (e < json.Length && (char.IsDigit(json[e]) || json[e] == '-')) e++;
            return int.TryParse(json.Substring(j, e - j), NumberStyles.Integer, CultureInfo.InvariantCulture, out value);
        }

        static bool TryReadDouble(string json, string key, out double value)
        {
            value = 0;
            string pat = "\"" + key + "\"";
            int k = json.IndexOf(pat, StringComparison.OrdinalIgnoreCase);
            if (k < 0) return false;
            int colon = json.IndexOf(':', k + pat.Length);
            if (colon < 0) return false;
            int j = colon + 1;
            while (j < json.Length && (json[j] == ' ' || json[j] == '\t')) j++;
            int e = j;
            while (e < json.Length && (char.IsDigit(json[e]) || json[e] == '-' || json[e] == '+' || json[e] == '.' || json[e] == 'e' || json[e] == 'E'))
                e++;
            return double.TryParse(json.Substring(j, e - j), NumberStyles.Float, CultureInfo.InvariantCulture, out value);
        }

        static bool TryReadString(string json, string key, out string value)
        {
            value = "";
            string pat = "\"" + key + "\"";
            int k = json.IndexOf(pat, StringComparison.OrdinalIgnoreCase);
            if (k < 0) return false;
            int colon = json.IndexOf(':', k + pat.Length);
            if (colon < 0) return false;
            int q1 = json.IndexOf('"', colon + 1);
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

        public static bool TrySave(WorldSession session, RealEarthConfig? cfg, string? path = null)
        {
            try
            {
                var snap = Capture(session, cfg);
                string json = snap.ToJson() + "\n";
                // Dual-write: stock world save dir (primary) + mod Config fallback.
                var paths = new List<string>();
                if (!string.IsNullOrEmpty(path))
                    paths.Add(path!);
                else
                {
                    paths.Add(PreferredSessionPath());
                    string fallback = DefaultSessionPath();
                    if (!string.Equals(paths[0], fallback, StringComparison.OrdinalIgnoreCase))
                        paths.Add(fallback);
                }
                bool any = false;
                foreach (var p in paths)
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
                var paths = new List<string>();
                if (!string.IsNullOrEmpty(path))
                    paths.Add(path!);
                else
                {
                    // Prefer world save, then mod Config.
                    paths.Add(PreferredSessionPath());
                    string fallback = DefaultSessionPath();
                    if (!string.Equals(paths[0], fallback, StringComparison.OrdinalIgnoreCase))
                        paths.Add(fallback);
                }
                foreach (var p in paths)
                {
                    if (!File.Exists(p)) continue;
                    string json = File.ReadAllText(p);
                    if (!SessionSnapshot.TryParse(json, out var snap)) continue;
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
