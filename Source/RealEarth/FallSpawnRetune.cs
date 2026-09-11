using System;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// Soft gap 35/36: one-shot spawn surface snap + FallDamageModifier scale,
    /// continuous kill-plane rescue when Y falls far below surface, plus
    /// one-shot VehicleManager surface snap at extreme Y (soft gap 36).
    /// FindSpawnPointAtXZ already rides the YDim expand (255→32767).
    /// </summary>
    internal static class FallSpawnRetune
    {
        static bool _spawnSnapDone;
        static bool _vehicleSnapDone;
        static bool _fallScaleApplied;
        static bool _loggedMissingFall;
        static FieldInfo? _fallDamageModifier;
        const int KillPlaneMinIntervalMs = 500;
        static int _lastKillPlaneMs;

        /// <summary>Reset on WorldReady so a new world can snap again.</summary>
        public static void ResetSession()
        {
            _spawnSnapDone = false;
            _vehicleSnapDone = false;
            _fallScaleApplied = false;
        }

        /// <summary>
        /// Apply FallDamageModifierScale once per session (stock field is static).
        /// </summary>
        public static void EnsureFallDamageScale()
        {
            if (_fallScaleApplied) return;
            var cfg = ModApi.Config;
            if (cfg == null) return;
            float scale = cfg.FallDamageModifierScale;
            if (scale <= 0f || Math.Abs(scale - 1f) < 1e-4f)
            {
                _fallScaleApplied = true;
                return;
            }

            try
            {
                if (_fallDamageModifier == null)
                {
                    var t = EngineReflection.FindType("EntityPlayer")
                        ?? EngineReflection.FindType("EntityPlayerLocal");
                    if (t == null)
                    {
                        if (!_loggedMissingFall)
                        {
                            ModApi.Log("FallSpawnRetune: EntityPlayer type missing; fall scale idle");
                            _loggedMissingFall = true;
                        }
                        return;
                    }
                    // Static field: ReflectCache.Field is instance-only.
                    const BindingFlags staticAny =
                        BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
                    for (Type? bt = t; bt != null && _fallDamageModifier == null; bt = bt.BaseType)
                        _fallDamageModifier = bt.GetField("FallDamageModifier", staticAny);
                }
                if (_fallDamageModifier == null || !_fallDamageModifier.IsStatic)
                {
                    if (!_loggedMissingFall)
                    {
                        ModApi.Log("FallSpawnRetune: FallDamageModifier field missing; fall scale idle");
                        _loggedMissingFall = true;
                    }
                    _fallScaleApplied = true;
                    return;
                }

                object? curObj = _fallDamageModifier.GetValue(null);
                float cur = curObj is float f ? f : 1f;
                float next = cur * scale;
                if (next < 0.05f) next = 0.05f;
                if (next > 2f) next = 2f;
                _fallDamageModifier.SetValue(null, next);
                _fallScaleApplied = true;
                ModApi.Log(
                    $"FallSpawnRetune: FallDamageModifier {cur:0.###} → {next:0.###} " +
                    $"(scale={scale:0.###})");
            }
            catch (Exception ex)
            {
                ModApi.LogError($"FallSpawnRetune fall scale: {ex.GetType().Name}: {ex.Message}");
                _fallScaleApplied = true;
            }
        }

        /// <summary>
        /// One-shot: if local player Y is far from sampled surface, snap to surface+1.
        /// </summary>
        public static void TrySnapSpawnToSurface(object entity, int localX, int localY, int localZ)
        {
            if (_spawnSnapDone) return;
            var cfg = ModApi.Config;
            var session = ModApi.Session;
            if (cfg == null || !cfg.SnapSpawnToSurface) 
            {
                _spawnSnapDone = true;
                return;
            }
            if (session == null || !session.IsStreamed)
            {
                _spawnSnapDone = true;
                return;
            }

            try
            {
                int surface = ChunkTerrainSampler.SampleGameHeightInt(localX, localZ);
                if (surface <= 0)
                    return; // tiles not ready yet; retry next tick

                int targetY = surface + 1;
                int delta = Math.Abs(localY - targetY);
                // Only snap when clearly wrong (buried / floating / stock ~64-250 band).
                if (delta < 8)
                {
                    _spawnSnapDone = true;
                    return;
                }

                if (!EngineReflection.TrySetPos(entity, localX, targetY, localZ))
                {
                    ModApi.Log(
                        $"FallSpawnRetune: surface snap failed at ({localX},{localZ}) " +
                        $"y={localY}→{targetY}");
                    return;
                }

                _spawnSnapDone = true;
                ModApi.Log(
                    $"FallSpawnRetune: snapped spawn Y {localY}→{targetY} " +
                    $"(surface={surface} at local=({localX},{localZ}))");
            }
            catch (Exception ex)
            {
                ModApi.LogError($"FallSpawnRetune snap: {ex.GetType().Name}: {ex.Message}");
                _spawnSnapDone = true;
            }
        }

        /// <summary>
        /// Soft gap 36: one-shot snap for VehicleManager vehicles whose Y is far
        /// from sampled surface (buried / floating on tall 1:1 height). Best-effort
        /// reflection; retries while tiles are not ready. Caps work per call.
        /// </summary>
        public static void TrySnapVehiclesToSurface()
        {
            if (_vehicleSnapDone) return;
            var cfg = ModApi.Config;
            var session = ModApi.Session;
            if (cfg == null || !cfg.SnapVehicleToSurface)
            {
                _vehicleSnapDone = true;
                return;
            }
            if (session == null || !session.IsStreamed)
            {
                _vehicleSnapDone = true;
                return;
            }

            try
            {
                Type? t = EngineReflection.FindType("VehicleManager");
                if (t == null)
                {
                    _vehicleSnapDone = true;
                    return;
                }
                object? inst = t.GetProperty("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null)
                    ?? t.GetField("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null);
                if (inst == null)
                    return; // manager not ready yet; retry next tick

                object? coll = null;
                foreach (var pname in new[] { "vehicles", "Vehicles", "list", "List", "activeVehicles" })
                {
                    var p = inst.GetType().GetProperty(pname, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    var f = inst.GetType().GetField(pname, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    coll = p?.GetValue(inst) ?? f?.GetValue(inst);
                    if (coll != null) break;
                }
                if (coll == null)
                {
                    _vehicleSnapDone = true;
                    return;
                }

                int snapped = 0;
                int scanned = 0;
                int waiting = 0;
                const int MaxScan = 32;
                if (coll is System.Collections.IEnumerable en)
                {
                    foreach (object? item in en)
                    {
                        if (item == null) continue;
                        // Some managers store wrappers; prefer entity-like objects with a position.
                        object entity = item;
                        scanned++;
                        if (scanned > MaxScan) break;
                        if (!EngineReflection.TryGetPos(entity, out int vx, out int vy, out int vz))
                            continue;
                        int surface = ChunkTerrainSampler.SampleGameHeightInt(vx, vz);
                        if (surface <= 0)
                        {
                            waiting++;
                            continue;
                        }
                        int targetY = surface + 1;
                        if (Math.Abs(vy - targetY) < 8)
                            continue;
                        if (EngineReflection.TrySetPos(entity, vx, targetY, vz))
                        {
                            snapped++;
                            ModApi.Log(
                                $"FallSpawnRetune: vehicle snap Y {vy}→{targetY} " +
                                $"(surface={surface} at local=({vx},{vz}))");
                        }
                    }
                }

                // Done when we scanned a set and none are waiting on tiles.
                if (waiting == 0)
                    _vehicleSnapDone = true;
                else if (snapped > 0)
                    ModApi.Log($"FallSpawnRetune: vehicle snap pending tiles (snapped={snapped}, waiting={waiting})");
            }
            catch (Exception ex)
            {
                ModApi.LogError($"FallSpawnRetune vehicle snap: {ex.GetType().Name}: {ex.Message}");
                _vehicleSnapDone = true;
            }
        }

        /// <summary>
        /// Soft gap 35: if local player Y is more than KillPlaneDepthBlocks below
        /// sampled surface, snap to surface+1 (fallen through / void). Throttled.
        /// </summary>
        public static void TryKillPlaneRescue(object entity, int localX, int localY, int localZ)
        {
            var cfg = ModApi.Config;
            var session = ModApi.Session;
            if (cfg == null || !cfg.KillPlaneRescue)
                return;
            if (session == null || !session.IsStreamed)
                return;

            int now = Environment.TickCount;
            if (_lastKillPlaneMs != 0 && unchecked(now - _lastKillPlaneMs) < KillPlaneMinIntervalMs)
                return;

            try
            {
                int surface = ChunkTerrainSampler.SampleGameHeightInt(localX, localZ);
                if (surface <= 0)
                    return; // tiles not ready

                int depth = cfg.KillPlaneDepthBlocks;
                if (depth < 8) depth = 64;
                if (localY >= surface - depth)
                    return;

                int targetY = surface + 1;
                _lastKillPlaneMs = now;
                if (!EngineReflection.TrySetPos(entity, localX, targetY, localZ))
                {
                    ModApi.Log(
                        $"FallSpawnRetune: kill-plane rescue failed at ({localX},{localZ}) " +
                        $"y={localY}→{targetY}");
                    return;
                }

                ModApi.Log(
                    $"FallSpawnRetune: kill-plane rescue Y {localY}→{targetY} " +
                    $"(surface={surface}, depth={depth} at local=({localX},{localZ}))");
            }
            catch (Exception ex)
            {
                ModApi.LogError($"FallSpawnRetune kill-plane: {ex.GetType().Name}: {ex.Message}");
                _lastKillPlaneMs = now;
            }
        }

    }
}
