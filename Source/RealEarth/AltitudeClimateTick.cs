using System;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// Player-tick altitude climate: hypoxia + cold + heat from elev ASL /
    /// latitude / landcover. Applies buffs via EntityBuffs reflection; reuses
    /// drowning oxygen UI for hypoxia (buffAltitudeHypoxia*). Local/primary only.
    /// </summary>
    internal static class AltitudeClimateTick
    {
        const string CvarElevM = "_re_elev_m";
        const string CvarTempC = "_re_ambient_temp_c";
        const string CvarO2 = "_re_oxygen_sat";
        const string CvarHypoxiaBand = "_re_hypoxia_band";
        const string CvarColdBand = "_re_cold_band";
        const string CvarHeatBand = "_re_heat_band";

        const string BuffHypoxiaMild = "buffAltitudeHypoxia01";
        const string BuffHypoxiaSevere = "buffAltitudeHypoxia02";
        const string BuffHypoxiaCritical = "buffAltitudeHypoxia03";
        const string BuffColdMild = "buffAltitudeCold01";
        const string BuffColdSevere = "buffAltitudeCold02";
        const string BuffHeatMild = "buffAltitudeHeat01";
        const string BuffHeatSevere = "buffAltitudeHeat02";

        static readonly string[] HypoxiaBuffs =
        {
            BuffHypoxiaMild, BuffHypoxiaSevere, BuffHypoxiaCritical
        };

        static readonly string[] ColdBuffs =
        {
            BuffColdMild, BuffColdSevere
        };

        static readonly string[] HeatBuffs =
        {
            BuffHeatMild, BuffHeatSevere
        };

        // Throttle: climate does not need every frame; 1 Hz is enough.
        const int MinIntervalMs = 1000;
        static int _lastTickMs;

        /// <summary>
        /// Millisecond tick source with Environment.TickCount semantics (unchecked
        /// wrap-safe deltas). Injectable so the throttle can be stepped by virtual
        /// time in a deterministic harness instead of wall clock.
        /// </summary>
        internal static Func<int> TickNow { get; set; } = static () => Environment.TickCount;

        // Resolution flag publishes last (see EnsureMethods) and every handle is
        // volatile, so a caller on another thread can never observe "resolved" paired
        // with a half-filled handle set.
        static volatile MethodInfo? _addBuff;
        static volatile MethodInfo? _removeBuff;
        static volatile MethodInfo? _setCustomVar;
        static volatile PropertyInfo? _buffsProp;
        static volatile bool _resolved;
        static volatile bool _loggedMissing;

        /// <summary>
        /// Apply altitude climate for a local player. Safe to call every tick;
        /// internally throttled. No-ops when session/config unavailable.
        /// </summary>
        public static void TickPlayer(object entity, int localX, int gameY, int localZ)
        {
            try
            {
                int now = TickNow();
                if (_lastTickMs != 0 && unchecked(now - _lastTickMs) < MinIntervalMs)
                    return;
                _lastTickMs = now;

                var cfg = ModApi.Config;
                var session = ModApi.Session;
                if (cfg == null || session == null)
                    return;

                // Sample the DEM column, do not re-derive meters from gameY: the
                // identity gameY - sea only holds under a 1:1 height policy, and
                // the compressed opt-in modes clamp Y to 255, which read as
                // -15745 m and invert every band.
                float elevMeters = 0f;
                try
                {
                    ChunkTerrainSampler.SampleSurfaceMeters(localX, localZ, out elevMeters);
                }
                catch (Exception ex)
                {
                    // No sample: climate falls back to sea-level lapse only.
                    ModApi.LogError(
                        $"AltitudeClimateTick: surface sample failed: {ex.GetType().Name}: {ex.Message}");
                    elevMeters = 0f;
                }
                int elevM = (int)Math.Round(elevMeters);

                float latDeg = 0f;
                try
                {
                    session.LocalToEarth(localX, localZ, out int earthX, out int earthZ);
                    session.EarthToLonLat(earthX, earthZ, out _, out double lat);
                    latDeg = (float)lat;
                }
                catch
                {
                    // Lat optional: ISA from sea-level base still applies.
                }

                // Soft gap 24: landcover offset on ambient (desert hotter, snow colder).
                byte lc = 255;
                try
                {
                    lc = ChunkTerrainSampler.SampleLandcover(localX, localZ);
                }
                catch
                {
                    // Missing tiles: lat+lapse only.
                }

                float ambient = AltitudeClimate.AmbientTempC(elevM, latDeg, lc);
                float o2 = AltitudeClimate.OxygenSaturation(elevM);
                int hypoxia = AltitudeClimate.HypoxiaBand(elevM);
                int cold = AltitudeClimate.ColdBand(ambient);
                int heat = AltitudeClimate.HeatBand(ambient);

                if (!TryResolveBuffs(entity, out object? buffs) || buffs == null)
                    return;

                SetCVar(buffs, CvarElevM, elevM);
                SetCVar(buffs, CvarTempC, ambient);
                SetCVar(buffs, CvarO2, o2);
                SetCVar(buffs, CvarHypoxiaBand, hypoxia);
                SetCVar(buffs, CvarColdBand, cold);
                SetCVar(buffs, CvarHeatBand, heat);

                ApplyBand(buffs, HypoxiaBuffs, hypoxia);
                ApplyBand(buffs, ColdBuffs, cold);
                ApplyBand(buffs, HeatBuffs, heat);
            }
            catch (Exception ex)
            {
                ModApi.LogError($"AltitudeClimateTick: {ex.GetType().Name}: {ex.Message}");
            }
        }

        static void ApplyBand(object buffs, string[] names, int band)
        {
            // band 0 = none; band N = names[N-1] active, others removed.
            for (int i = 0; i < names.Length; i++)
            {
                if (band == i + 1)
                    AddBuff(buffs, names[i]);
                else
                    RemoveBuff(buffs, names[i]);
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
                    ModApi.Log("AltitudeClimateTick: EntityBuffs not found; altitude buffs idle");
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
            // Resolve into locals, then publish the flag last: a reader that sees
            // _resolved set must see the full handle set, and a throw mid-resolve must
            // leave the flag clear so the next tick retries instead of latching a
            // half-resolved cache.
            PropertyInfo? buffsProp;
            MethodInfo? addBuff;
            MethodInfo? removeBuff;
            MethodInfo? setCustomVar;
            try
            {
                buffsProp = ReflectCache.Prop(entityType, "Buffs")
                    ?? ReflectCache.PropPub(entityType, "Buffs");
                // Walk base types for EntityAlive.Buffs.
                for (Type? t = entityType; t != null && buffsProp == null; t = t.BaseType)
                {
                    buffsProp = ReflectCache.Prop(t, "Buffs")
                        ?? ReflectCache.PropPub(t, "Buffs");
                }
                addBuff = null;
                removeBuff = null;
                setCustomVar = null;
                if (buffsProp != null)
                {
                    Type buffsType = buffsProp.PropertyType;
                    foreach (var m in buffsType.GetMethods(BindingFlags.Instance | BindingFlags.Public))
                    {
                        if (m.Name == "AddBuff" && addBuff == null)
                        {
                            var ps = m.GetParameters();
                            // Prefer: AddBuff(string, Vector3i, int, bool, bool, float)
                            if (ps.Length == 6 && ps[0].ParameterType == typeof(string))
                                addBuff = m;
                            else if (ps.Length == 1 && ps[0].ParameterType == typeof(string))
                                addBuff = m;
                        }
                        else if (m.Name == "RemoveBuff" && removeBuff == null)
                        {
                            var ps = m.GetParameters();
                            if (ps.Length >= 1 && ps[0].ParameterType == typeof(string))
                                removeBuff = m;
                        }
                        else if (m.Name == "SetCustomVar" && setCustomVar == null)
                        {
                            var ps = m.GetParameters();
                            if (ps.Length >= 2 && ps[0].ParameterType == typeof(string)
                                && ps[1].ParameterType == typeof(float))
                                setCustomVar = m;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                ModApi.LogError($"AltitudeClimateTick resolve: {ex.GetType().Name}: {ex.Message}");
                return;
            }
            _buffsProp = buffsProp;
            _addBuff = addBuff;
            _removeBuff = removeBuff;
            _setCustomVar = setCustomVar;
            _resolved = true;
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

        static void AddBuff(object buffs, string name)
        {
            if (_addBuff == null) return;
            try
            {
                var ps = _addBuff.GetParameters();
                if (ps.Length == 1)
                {
                    _addBuff.Invoke(buffs, new object?[] { name });
                    return;
                }
                if (ps.Length == 6)
                {
                    // name, Vector3i pos, instigatorId, netSync, fromElectrical, duration
                    object pos = Activator.CreateInstance(ps[1].ParameterType)!;
                    _addBuff.Invoke(buffs, new object?[] { name, pos, -1, false, false, -1f });
                }
            }
            catch { /* best-effort */ }
        }

        static void RemoveBuff(object buffs, string name)
        {
            if (_removeBuff == null) return;
            try
            {
                var ps = _removeBuff.GetParameters();
                if (ps.Length == 1)
                    _removeBuff.Invoke(buffs, new object?[] { name });
                else if (ps.Length >= 3)
                    _removeBuff.Invoke(buffs, new object?[] { name, -1, false });
                else if (ps.Length == 2)
                    _removeBuff.Invoke(buffs, new object?[] { name, -1 });
            }
            catch { /* best-effort */ }
        }
    }
}
