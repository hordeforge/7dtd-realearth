using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;

namespace RealEarth
{
    /// <summary>
    /// Fail-closed build guard: RealEarth hashes Assembly-CSharp.dll at init and
    /// compares it against a reviewed allowlist of known game builds. An unknown
    /// build blocks height inject unless the operator explicitly opts in
    /// (EngineHeightAllowUnknownBuild). This catches a game update that changed
    /// the assembly before the mod's hooks are re-verified against the new build.
    ///
    /// The list means "hooks were verified against this exact assembly", not
    /// "this is the current build". Rows therefore stay after a retarget: the
    /// b9 and b10 rows below are reviewed history, and the b18 rows are the
    /// current pin (docs/GAME_VERSION.md). The b18 client binding was checked
    /// against the installed client assembly (every reflection hook target
    /// present, monodis, 2026-10-24); no b18 client boot has run yet.
    /// </summary>
    public static class BuildGuard
    {
        /// <summary>Reviewed build allowlist: sha256 of Assembly-CSharp.dll -> human label.</summary>
        static readonly Dictionary<string, string> ReviewedBuilds =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                {"fceec27300ffd3a1f97b097e43b60f3b07597f441e7ecbc6e1b59eebb234c705", "V3.3.0 (b18) live client"},
                {"e16ff9d539b8fbf64904c0bc090d502286a62464742a9396f0455936ad0beb87", "V3.3.0 (b18) live dedi"},
                {"3737eedc9f143d428a69030317428c45d342be4f11006a46d72bcd7b1d0fc64d", "V3.2.0 (b10) live dedi"},
                {"70c669bec3cb11d1d8fabd2cc4f871d1eca21e27d3a185afe3efa71e571cabd6", "V3.2.0 (b9) stock (dedi bak)"},
                {"feff12e779d5939a2b06a637f12e820ddc28c60da5aa3630733cc7ce5252badb", "V3.2.0 (b9) live client"},
                {"a01a95393b24b75adf1e4b3ee1391ba19fa61e6bad79271fa95d8df721720837", "V3.2.0 (b9) live dedi"},
            };

        // Volatile: Init publishes the verdict on the init thread while
        // RuntimeHooks.EnforceInjectGate reads Blocked (and console/init paths read the
        // rest). A stale false on an unreviewed build lets height inject run, which is
        // exactly what the guard exists to stop.
        /// <summary>True once Init has run (the hash verdict lives in BuildKnown/Blocked).</summary>
        public static volatile bool Guarded;

        /// <summary>True when the current DLL hash is in the reviewed allowlist.</summary>
        public static volatile bool BuildKnown;

        /// <summary>Sha256 of the Assembly-CSharp.dll that was checked (lowercase hex).</summary>
        public static volatile string CurrentSha = "";

        /// <summary>True when an unknown build should be refused (fail-closed).</summary>
        public static volatile bool Blocked;

        static volatile string? _assemblyPath;

        /// <summary>Path to the loaded Assembly-CSharp.dll, or "" when it is not loaded yet.</summary>
        public static string AssemblyPath
        {
            get
            {
                if (_assemblyPath != null) return _assemblyPath;
                try
                {
                    foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                    {
                        var n = asm.GetName().Name ?? "";
                        if (n.Equals("Assembly-CSharp", StringComparison.OrdinalIgnoreCase))
                        {
                            _assemblyPath = asm.Location;
                            return _assemblyPath;
                        }
                    }
                }
                catch { /* fall through */ }
                _assemblyPath = "";
                return _assemblyPath;
            }
        }

        /// <summary>
        /// Hash and check the loaded Assembly-CSharp against the reviewed list.
        /// Returns false when the build is unknown and not allowed. Fail-closed:
        /// any error (missing DLL, IO, hash) counts as unknown.
        /// </summary>
        public static bool Init(bool allowUnknownBuild)
        {
            // Fail closed for the whole hash window: a reader on another thread that
            // runs before the verdict lands must see "blocked", not the previous
            // world's "allowed". Every exit below overwrites this with the real verdict.
            Guarded = true;
            BuildKnown = false;
            Blocked = true;
            try
            {
                string path = AssemblyPath;
                if (string.IsNullOrEmpty(path) || !File.Exists(path))
                {
                    ModLog.LogWarn("BuildGuard: Assembly-CSharp.dll not found; build treated as UNKNOWN.");
                    Blocked = !allowUnknownBuild;
                    return !Blocked;
                }
                CurrentSha = Sha256OfFile(path);
                BuildKnown = ReviewedBuilds.ContainsKey(CurrentSha);
                if (BuildKnown)
                {
                    ModLog.Log(
                        $"BuildGuard: Assembly-CSharp build reviewed ({ReviewedBuilds[CurrentSha]}).");
                    Blocked = false;
                    return true;
                }
                Blocked = !allowUnknownBuild;
                ModLog.LogWarn(
                    $"BuildGuard: Assembly-CSharp build UNKNOWN (sha256={CurrentSha.Substring(0, 16)}...). " +
                    (Blocked
                        ? "Height inject BLOCKED (fail-closed). Review the new build, then set " +
                          "EngineHeightAllowUnknownBuild=true, or refresh the reviewed list."
                        : "Operator override EngineHeightAllowUnknownBuild=true: proceeding."));
                return !Blocked;
            }
            catch (Exception ex)
            {
                Blocked = !allowUnknownBuild;
                ModLog.LogError("BuildGuard: hash failed, build treated as UNKNOWN", ex);
                return !Blocked;
            }
        }

        static string Sha256OfFile(string path)
        {
            using var sha = SHA256.Create();
            using var fs = new FileStream(
                path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            var hash = sha.ComputeHash(fs);
            var sb = new System.Text.StringBuilder(hash.Length * 2);
            foreach (byte b in hash)
                sb.Append(b.ToString("x2"));
            return sb.ToString();
        }
    }
}
