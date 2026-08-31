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
    /// </summary>
    public static class BuildGuard
    {
        /// <summary>Reviewed build allowlist: sha256 of Assembly-CSharp.dll -> human label.</summary>
        static readonly Dictionary<string, string> ReviewedBuilds =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                {"70c669bec3cb11d1d8fabd2cc4f871d1eca21e27d3a185afe3efa71e571cabd6", "V3.2.0 (b9) stock (dedi bak)"},
                {"feff12e779d5939a2b06a637f12e820ddc28c60da5aa3630733cc7ce5252badb", "V3.2.0 (b9) live client"},
                {"a01a95393b24b75adf1e4b3ee1391ba19fa61e6bad79271fa95d8df721720837", "V3.2.0 (b9) live dedi"},
            };

        /// <summary>True after init; the DLL was hashed and checked.</summary>
        public static bool Guarded;

        /// <summary>True when the current DLL hash is in the reviewed allowlist.</summary>
        public static bool BuildKnown;

        /// <summary>Sha256 of the Assembly-CSharp.dll that was checked (lowercase hex).</summary>
        public static string CurrentSha = "";

        /// <summary>True when an unknown build should be refused (fail-closed).</summary>
        public static bool Blocked;

        static string? _assemblyPath;

        /// <summary>Path to Assembly-CSharp.dll as loaded (or the mod's game dir).</summary>
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
            Guarded = true;
            BuildKnown = false;
            Blocked = false;
            try
            {
                string path = AssemblyPath;
                if (string.IsNullOrEmpty(path) || !File.Exists(path))
                {
                    ModApi.LogWarn("BuildGuard: Assembly-CSharp.dll not found; build treated as UNKNOWN.");
                    Blocked = !allowUnknownBuild;
                    return !Blocked;
                }
                CurrentSha = Sha256OfFile(path);
                BuildKnown = ReviewedBuilds.ContainsKey(CurrentSha);
                if (BuildKnown)
                {
                    ModApi.Log(
                        $"BuildGuard: Assembly-CSharp build reviewed ({ReviewedBuilds[CurrentSha]}).");
                    Blocked = false;
                    return true;
                }
                Blocked = !allowUnknownBuild;
                ModApi.LogWarn(
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
                ModApi.LogError($"BuildGuard: hash failed ({ex.GetType().Name}: {ex.Message}); " +
                                "build treated as UNKNOWN.");
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
