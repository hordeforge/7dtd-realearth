using System;
using System.Collections.Concurrent;
using System.Linq;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// Shared reflection helpers for engine interop: type lookup by full/short name,
    /// floor division for chunk math, and entity position read/write via common member
    /// names. One implementation instead of the per-file copies that had drifted
    /// (cached vs uncached scans, differing null guards, supersets of fallbacks).
    /// </summary>
    internal static class EngineReflection
    {
        static readonly ConcurrentDictionary<(string Name, string? AsmHint), Type?> TypeCache =
            new ConcurrentDictionary<(string, string?), Type?>();

        /// <summary>
        /// Find a game type by full or short name across loaded assemblies (memoized;
        /// misses are cached too). ReflectionTypeLoadException-safe.
        /// </summary>
        internal static Type? FindType(string name, string? asmHint = null)
            => TypeCache.GetOrAdd((name, asmHint), static k => ScanForType(k.Name, k.AsmHint));

        static Type? ScanForType(string name, string? asmHint)
        {
            // Pass 1: exact full name via GetType (no type enumeration).
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (asmHint != null
                    && !string.Equals(asm.GetName().Name, asmHint, StringComparison.OrdinalIgnoreCase))
                    continue;
                try
                {
                    var t = asm.GetType(name, false);
                    if (t != null) return t;
                }
                catch { /* ignore */ }
            }

            // Pass 2: short-name scan when the caller passed a bare name.
            int lastDot = name.LastIndexOf('.');
            string shortName = lastDot >= 0 ? name.Substring(lastDot + 1) : name;
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    foreach (var t in asm.GetTypes())
                        if (t.Name == shortName || t.FullName == name)
                            return t;
                }
                catch (ReflectionTypeLoadException ex)
                {
                    foreach (var t in ex.Types ?? Array.Empty<Type>())
                        if (t != null && (t.Name == shortName || t.FullName == name))
                            return t;
                }
                catch { /* ignore */ }
            }
            return null;
        }

        /// <summary>Floor division; negative block coords must not truncate toward zero.</summary>
        internal static int FloorDiv(int a, int b) => a >= 0 ? a / b : (a - (b - 1)) / b;

        /// <summary>
        /// Assembly types with the partial-load fallback: ReflectionTypeLoadException
        /// still yields the types that did load.
        /// </summary>
        internal static Type[] SafeGetTypes(Assembly asm)
        {
            try
            {
                return asm.GetTypes();
            }
            catch (ReflectionTypeLoadException ex)
            {
                return (ex.Types ?? Array.Empty<Type>()).Where(t => t != null).Cast<Type>().ToArray();
            }
        }

        /// <summary>Entity world position via common position members. False when absent.</summary>
        internal static bool TryGetPos(object entity, out int x, out int y, out int z)
        {
            x = y = z = 0;
            try
            {
                var t = entity.GetType();
                object? pos = ReflectCache.PropPub(t, "position")?.GetValue(entity, null)
                    ?? ReflectCache.PropPub(t, "Position")?.GetValue(entity, null)
                    ?? ReflectCache.Field(t, "position")?.GetValue(entity)
                    ?? ReflectCache.Field(t, "Position")?.GetValue(entity);
                if (pos == null) return false;
                x = ReadComp(pos, "x");
                y = ReadComp(pos, "y");
                z = ReadComp(pos, "z");
                return true;
            }
            catch { return false; }
        }

        static int ReadComp(object vec, string name)
        {
            var t = vec.GetType();
            var f = ReflectCache.Field(t, name);
            if (f != null)
                return ToFloorInt(f.GetValue(vec));
            var p = ReflectCache.PropPub(t, name);
            if (p != null)
                return ToFloorInt(p.GetValue(vec, null));
            return 0;
        }

        static int ToFloorInt(object? v)
        {
            switch (v)
            {
                case float fl: return (int)Math.Floor(fl);
                case double d: return (int)Math.Floor(d);
                case null: return 0;
                default: return Convert.ToInt32(v);
            }
        }

        /// <summary>
        /// Move an entity via SetPosition/SetPos(Vector-like); falls back to a direct
        /// write on a readable position field. False when nothing accepted the write.
        /// </summary>
        internal static bool TrySetPos(object entity, int x, int y, int z)
        {
            try
            {
                var t = entity.GetType();
                foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                {
                    if (m.Name != "SetPosition" && m.Name != "SetPos") continue;
                    var ps = m.GetParameters();
                    if (ps.Length != 1) continue;
                    var vec = Activator.CreateInstance(ps[0].ParameterType);
                    if (vec == null) continue;
                    ReflectCache.WriteComp(vec, "x", x);
                    ReflectCache.WriteComp(vec, "y", y);
                    ReflectCache.WriteComp(vec, "z", z);
                    m.Invoke(entity, new[] { vec });
                    return true;
                }
                // Direct position field write
                var posField = ReflectCache.Field(t, "position");
                object? pos = posField?.GetValue(entity);
                if (pos != null)
                {
                    if (!pos.GetType().IsValueType)
                    {
                        // Reference position: member writes mutate the live object.
                        ReflectCache.WriteComp(pos, "x", x);
                        ReflectCache.WriteComp(pos, "y", y);
                        ReflectCache.WriteComp(pos, "z", z);
                        return true;
                    }
                    // Struct position: GetValue boxes a copy, so component writes on
                    // that box never reach the entity. Mutate the box and store it
                    // back; without this the method reported success while nothing
                    // moved (origin-slide rollback never triggered).
                    ReflectCache.WriteComp(pos, "x", x);
                    ReflectCache.WriteComp(pos, "y", y);
                    ReflectCache.WriteComp(pos, "z", z);
                    try
                    {
                        posField!.SetValue(entity, pos);
                        return true;
                    }
                    catch { /* fall through: report failure */ }
                }
            }
            catch { /* ignore */ }
            return false;
        }
    }
}
