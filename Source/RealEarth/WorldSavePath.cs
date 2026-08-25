using System;
using System.IO;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// Resolve stock 7DTD save directory (GameIO.GetSaveGameDir) for durable session files.
    /// Falls back to mod Config/ when the game path is not available.
    /// </summary>
    public static class WorldSavePath
    {
        public const string SessionFileName = "realearth.session.json";

        /// <summary>
        /// Prefer &lt;saveGameDir&gt;/realearth.session.json, else mod Config path.
        /// </summary>
        public static string SessionPath()
        {
            string? saveDir = TryGetSaveGameDir();
            if (!string.IsNullOrEmpty(saveDir))
            {
                try
                {
                    if (!Directory.Exists(saveDir))
                        Directory.CreateDirectory(saveDir);
                    return Path.Combine(saveDir, SessionFileName);
                }
                catch { /* fall through */ }
            }
            return SessionStateStore.DefaultSessionPath();
        }

        /// <summary>
        /// Stable identity of the current world save (save dir path, else world name).
        /// Null when unavailable (offline / unit contexts). Session snapshots carry a
        /// hash of this so one world's position can never restore into another via the
        /// global mod Config fallback file.
        /// </summary>
        public static string? SessionScopeId()
        {
            string? dir = TryGetSaveGameDir();
            if (!string.IsNullOrEmpty(dir)) return dir;
            return TryWorldName();
        }

        public static string? TryGetSaveGameDir()
        {
            try
            {
                // GameIO.GetSaveGameDir() static
                Type? gameIo = EngineReflection.FindType("GameIO");
                if (gameIo != null)
                {
                    foreach (var mn in new[] { "GetSaveGameDir", "GetSaveGameDirectory", "GetPlayerDataDir" })
                    {
                        var m = gameIo.GetMethod(mn, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                        if (m == null || m.GetParameters().Length != 0) continue;
                        if (m.ReturnType != typeof(string)) continue;
                        var s = m.Invoke(null, null) as string;
                        if (!string.IsNullOrEmpty(s))
                            return s;
                    }
                }

                // GamePrefs / GameManager world name under UserData
                string? userData = TryUserDataFolder();
                string? worldName = TryWorldName();
                if (!string.IsNullOrEmpty(userData) && !string.IsNullOrEmpty(worldName))
                {
                    string candidate = Path.Combine(userData, "Saves", worldName);
                    if (Directory.Exists(candidate))
                        return candidate;
                    // Often Saves/<GameName>/<WorldName>
                    string saves = Path.Combine(userData, "Saves");
                    if (Directory.Exists(saves))
                    {
                        foreach (var sub in Directory.GetDirectories(saves))
                        {
                            string w = Path.Combine(sub, worldName);
                            if (Directory.Exists(w))
                                return w;
                        }
                    }
                }
            }
            catch { /* ignore */ }
            return null;
        }

        static string? TryUserDataFolder()
        {
            try
            {
                Type? gameIo = EngineReflection.FindType("GameIO");
                if (gameIo != null)
                {
                    foreach (var mn in new[] { "GetUserGameDataDir", "GetUserDataPath", "GetSaveGameRootDir" })
                    {
                        var m = gameIo.GetMethod(mn, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                        if (m != null && m.GetParameters().Length == 0 && m.ReturnType == typeof(string))
                        {
                            var s = m.Invoke(null, null) as string;
                            if (!string.IsNullOrEmpty(s)) return s;
                        }
                    }
                }
            }
            catch { /* ignore */ }
            // Common dedicated / client userdata
            string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            foreach (var p in new[]
            {
                Path.Combine(home, ".local", "share", "7DaysToDie"),
                Path.Combine(home, "Library", "Application Support", "7DaysToDie"),
                Path.Combine(home, "AppData", "Roaming", "7DaysToDie"),
            })
            {
                if (Directory.Exists(p)) return p;
            }
            return null;
        }

        static string? TryWorldName()
        {
            try
            {
                var gmType = Type.GetType("GameManager, Assembly-CSharp");
                var inst = gmType?.GetProperty("Instance")?.GetValue(null);
                var world = inst?.GetType().GetProperty("World")?.GetValue(inst);
                if (world != null)
                {
                    foreach (var pn in new[] { "Guid", "WorldName", "worldName", "Name" })
                    {
                        var p = world.GetType().GetProperty(pn);
                        var s = p?.GetValue(world)?.ToString();
                        // Reject both separators: this name is joined into save-dir
                        // probes and becomes a cross-platform session scope id, and
                        // '\' is a live separator on Windows game hosts.
                        if (!string.IsNullOrEmpty(s) && s!.Length < 128
                            && s.IndexOf('/') < 0 && s.IndexOf('\\') < 0)
                            return s;
                    }
                }
                // GamePrefs.GetString(EnumGamePrefs.GameWorld)
                Type? prefs = EngineReflection.FindType("GamePrefs");
                if (prefs != null)
                {
                    var getString = prefs.GetMethod("GetString", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                    if (getString != null)
                    {
                        // Try enum value by name
                        Type? enumT = EngineReflection.FindType("EnumGamePrefs");
                        if (enumT != null && enumT.IsEnum)
                        {
                            foreach (var name in new[] { "GameWorld", "GameName" })
                            {
                                try
                                {
                                    object ev = Enum.Parse(enumT, name);
                                    var s = getString.Invoke(null, new[] { ev }) as string;
                                    if (!string.IsNullOrEmpty(s)) return s;
                                }
                                catch { /* next */ }
                            }
                        }
                    }
                }
            }
            catch { /* ignore */ }
            return null;
        }
    }
}
