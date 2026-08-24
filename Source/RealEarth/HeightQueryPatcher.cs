using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// Pure selection rules for which GetTerrainHeight* methods to Harmony-patch.
    /// No early cap: RWG host uses TerrainGeneratorWithBiomeResource; baked uses TerrainFromRaw/DTM.
    /// Prefer concrete classes over ITerrainGenerator so virtual dispatch hits RealEarth samples.
    /// </summary>
    public static class HeightQueryPatcher
    {
        public static readonly string[] HeightMethodNames =
        {
            "GetTerrainHeightByteAt",
            "GetTerrainHeightAt",
            "GetTerrainHeight",
            "GetHeightAt",
        };

        /// <summary>Type name tokens that own terrain height queries on 3.0.x.</summary>
        public static readonly string[] PreferredConcreteTypeNames =
        {
            "TerrainGeneratorWithBiomeResource", // RWG / host Streamed path
            "TerrainFromRaw",
            "TerrainFromDTM",
            "TerrainFromImage",
        };

        public static bool IsHeightQueryMethodName(string name)
        {
            if (string.IsNullOrEmpty(name)) return false;
            for (int i = 0; i < HeightMethodNames.Length; i++)
            {
                if (string.Equals(name, HeightMethodNames[i], StringComparison.Ordinal))
                    return true;
            }
            return false;
        }

        public static bool IsTerrainRelatedTypeName(string name)
        {
            if (string.IsNullOrEmpty(name)) return false;
            if (name.IndexOf("TerrainFrom", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (name.IndexOf("TerrainGenerator", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (name.Equals("ITerrainGenerator", StringComparison.OrdinalIgnoreCase)) return true;
            if (name.Equals("HeightMap", StringComparison.OrdinalIgnoreCase)) return true;
            if (name.IndexOf("ChunkProvider", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (name.IndexOf("WorldGenerator", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (name.Equals("World", StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        /// <summary>
        /// Higher = patch earlier. Concrete preferred types first, then other concrete,
        /// then interfaces/abstract last (interfaces alone do not cover RWG dispatch).
        /// </summary>
        public static int TypePatchPriority(Type t)
        {
            if (t == null) return -1000;
            string n = t.Name;
            for (int i = 0; i < PreferredConcreteTypeNames.Length; i++)
            {
                if (string.Equals(n, PreferredConcreteTypeNames[i], StringComparison.Ordinal))
                    return 1000 - i;
            }
            if (t.IsInterface) return -50;
            if (t.IsAbstract) return -10;
            if (IsTerrainRelatedTypeName(n)) return 100;
            return 0;
        }

        public static bool IsPatchableHeightSignature(MethodInfo m)
        {
            if (m == null || m.IsAbstract || m.IsGenericMethodDefinition)
                return false;
            if (!IsHeightQueryMethodName(m.Name))
                return false;
            var ps = m.GetParameters();
            if (ps.Length < 2) return false;
            // (int,int) or (float,float) world XZ
            if (!IsCoordType(ps[0].ParameterType) || !IsCoordType(ps[1].ParameterType))
                return false;
            var rt = m.ReturnType;
            return rt == typeof(byte) || rt == typeof(int) || rt == typeof(float) || rt == typeof(double);
        }

        static bool IsCoordType(Type t) =>
            t == typeof(int) || t == typeof(float) || t == typeof(double);

        /// <summary>
        /// Discover all height-query methods on terrain-related types; concrete first, no cap.
        /// </summary>
        public static List<MethodInfo> DiscoverHeightQueryMethods(Assembly game)
        {
            var list = new List<MethodInfo>();
            if (game == null) return list;

            foreach (var t in EngineReflection.SafeGetTypes(game))
            {
                if (t == null || !IsTerrainRelatedTypeName(t.Name))
                    continue;
                MethodInfo[] methods;
                try
                {
                    methods = t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
                }
                catch
                {
                    continue;
                }
                foreach (var m in methods)
                {
                    if (IsPatchableHeightSignature(m))
                        list.Add(m);
                }
            }

            // Sort: concrete preferred types first
            list.Sort((a, b) =>
            {
                int pa = TypePatchPriority(a.DeclaringType!);
                int pb = TypePatchPriority(b.DeclaringType!);
                int c = pb.CompareTo(pa);
                if (c != 0) return c;
                c = string.CompareOrdinal(a.DeclaringType?.Name, b.DeclaringType?.Name);
                if (c != 0) return c;
                return string.CompareOrdinal(a.Name, b.Name);
            });
            return list;
        }

        /// <summary>Human-readable list for logs / offline audit.</summary>
        public static string FormatMethod(MethodInfo m)
        {
            if (m == null) return "?";
            var ps = m.GetParameters();
            string args = string.Join(",", ps.Select(p => p.ParameterType.Name));
            return $"{m.DeclaringType?.Name}.{m.Name}({args})->{m.ReturnType.Name}";
        }
    }
}
