using System;
using System.Collections.Concurrent;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// Memoized reflection lookups for per-frame hooks (player tick postfix runs every
    /// frame per player). Member metadata is stable for the process lifetime, so cache
    /// by (Type, name); misses (null) are cached too so failed probes do not rescan.
    /// Pub variants mirror plain Type.GetProperty/GetField (public instance only) and
    /// use separate dictionaries so the two flag sets never collide.
    /// </summary>
    public static class ReflectCache
    {
        const BindingFlags AnyInstance =
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

        static readonly ConcurrentDictionary<(Type, string), PropertyInfo?> Props =
            new ConcurrentDictionary<(Type, string), PropertyInfo?>();

        static readonly ConcurrentDictionary<(Type, string), FieldInfo?> Fields =
            new ConcurrentDictionary<(Type, string), FieldInfo?>();

        static readonly ConcurrentDictionary<(Type, string), PropertyInfo?> PubProps =
            new ConcurrentDictionary<(Type, string), PropertyInfo?>();

        /// <summary>Public+non-public instance lookup.</summary>
        public static PropertyInfo? Prop(Type t, string name)
            => Props.GetOrAdd((t, name), k => k.Item1.GetProperty(k.Item2, AnyInstance));

        /// <summary>Public-only instance lookup (mirrors plain Type.GetProperty).</summary>
        public static PropertyInfo? PropPub(Type t, string name)
            => PubProps.GetOrAdd((t, name), k => k.Item1.GetProperty(k.Item2));

        /// <summary>Public+non-public instance lookup.</summary>
        public static FieldInfo? Field(Type t, string name)
            => Fields.GetOrAdd((t, name), k => k.Item1.GetField(k.Item2, AnyInstance));

        public static bool TryReadIntMember(object obj, string name, out int value)
        {
            value = 0;
            var t = obj.GetType();
            var p = Prop(t, name);
            if (p != null && p.PropertyType == typeof(int))
            {
                value = (int)(p.GetValue(obj) ?? 0);
                return true;
            }
            var f = Field(t, name);
            if (f != null && f.FieldType == typeof(int))
            {
                value = (int)(f.GetValue(obj) ?? 0);
                return true;
            }
            return false;
        }

        /// <summary>GameManager.Instance.World via reflection (null when unavailable).</summary>
        public static object? GetEngineWorld()
        {
            try
            {
                var gmType = Type.GetType("GameManager, Assembly-CSharp");
                var inst = gmType?.GetProperty("Instance")?.GetValue(null);
                return inst?.GetType().GetProperty("World")?.GetValue(inst);
            }
            catch { return null; }
        }

        /// <summary>Set a named float member on a reflected Vector3-like struct.</summary>
        public static void WriteComp(object vec, string name, float value)
        {
            var t = vec.GetType();
            var f = t.GetField(name);
            if (f != null)
            {
                f.SetValue(vec, Convert.ChangeType(value, f.FieldType));
                return;
            }
            var p = t.GetProperty(name);
            if (p != null && p.CanWrite)
                p.SetValue(vec, Convert.ChangeType(value, p.PropertyType), null);
        }
    }
}
