using System;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// Soft gap 31: publish Earth lon/lat as EntityBuffs custom vars (~1 Hz)
    /// so XUi (or other HUD) can bind later. Console <c>relonlat</c>/<c>rll</c>
    /// remains the manual readout.
    /// </summary>
    internal static class LonLatHudTick
    {
        const string CvarLon = "_re_lon";
        const string CvarLat = "_re_lat";

        const int MinIntervalMs = 1000;
        static int _lastTickMs;

        /// <summary>
        /// Millisecond tick source with Environment.TickCount semantics (unchecked
        /// wrap-safe deltas). Injectable so the throttle can be stepped by virtual
        /// time in a deterministic harness instead of wall clock.
        /// </summary>
        internal static Func<int> TickNow { get; set; } = static () => Environment.TickCount;

        static MethodInfo? _setCustomVar;
        static PropertyInfo? _buffsProp;
        static bool _resolved;
        static bool _loggedMissing;

        /// <summary>
        /// Publish lon/lat cvars for a local/primary player. Throttled; no-ops
        /// when ShowLonLatHud is false or session/config is unavailable.
        /// </summary>
        public static void TickPlayer(object entity, int localX, int localZ)
        {
            try
            {
                int now = TickNow();
                if (_lastTickMs != 0 && unchecked(now - _lastTickMs) < MinIntervalMs)
                    return;
                _lastTickMs = now;

                var cfg = ModApi.Config;
                var session = ModApi.Session;
                if (cfg == null || session == null || !cfg.ShowLonLatHud)
                    return;
                if (!session.IsStreamed)
                    return;

                session.LocalToEarth(localX, localZ, out int earthX, out int earthZ);
                session.EarthToLonLat(earthX, earthZ, out double lon, out double lat);

                if (!TryResolveBuffs(entity, out object? buffs) || buffs == null)
                    return;

                SetCVar(buffs, CvarLon, (float)lon);
                SetCVar(buffs, CvarLat, (float)lat);
            }
            catch (Exception ex)
            {
                ModApi.LogError($"LonLatHudTick: {ex.GetType().Name}: {ex.Message}");
            }
        }

        static bool TryResolveBuffs(object entity, out object? buffs)
        {
            buffs = null;
            EnsureMethods(entity.GetType());
            if (_buffsProp == null)
            {
                if (!_loggedMissing)
                {
                    ModApi.Log("LonLatHudTick: EntityBuffs not found; lon/lat HUD idle");
                    _loggedMissing = true;
                }
                return false;
            }
            buffs = _buffsProp.GetValue(entity);
            return buffs != null;
        }

        static void EnsureMethods(Type entityType)
        {
            if (_resolved) return;
            _resolved = true;
            try
            {
                for (Type? t = entityType; t != null && _buffsProp == null; t = t.BaseType)
                {
                    _buffsProp = ReflectCache.Prop(t, "Buffs")
                        ?? ReflectCache.PropPub(t, "Buffs");
                }
                if (_buffsProp == null) return;

                Type buffsType = _buffsProp.PropertyType;
                foreach (var m in buffsType.GetMethods(BindingFlags.Instance | BindingFlags.Public))
                {
                    if (m.Name != "SetCustomVar" || _setCustomVar != null)
                        continue;
                    var ps = m.GetParameters();
                    if (ps.Length >= 2
                        && ps[0].ParameterType == typeof(string)
                        && ps[1].ParameterType == typeof(float))
                        _setCustomVar = m;
                }
            }
            catch (Exception ex)
            {
                ModApi.LogError($"LonLatHudTick resolve: {ex.GetType().Name}: {ex.Message}");
            }
        }

        static void SetCVar(object buffs, string name, float value)
        {
            if (_setCustomVar == null) return;
            try
            {
                var ps = _setCustomVar.GetParameters();
                object?[] args;
                if (ps.Length >= 5)
                {
                    // SetCustomVar(name, value, netSync, operation, forceSend)
                    args = new object?[] { name, value, false, 0, false };
                }
                else if (ps.Length == 3)
                    args = new object?[] { name, value, false };
                else if (ps.Length == 2)
                    args = new object?[] { name, value };
                else
                    return;
                _setCustomVar.Invoke(buffs, args);
            }
            catch { /* best-effort */ }
        }
    }
}
