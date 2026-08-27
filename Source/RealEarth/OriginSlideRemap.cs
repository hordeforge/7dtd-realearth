using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// After LocalWindow origin slides, remap simulated objects so absolute Earth stays fixed.
    /// Players, vehicles, dropped items, and land-claim block positions are adjusted by -dOrigin.
    /// Loaded chunk columns are rewritten by ChunkTerrainInject.ReinjectLoadedChunksAround
    /// (called from the slide path); unloaded chunks regenerate against the new origin.
    /// </summary>
    public static class OriginSlideRemap
    {
        static int _logBudget = 8;

        /// <summary>
        /// Remap every discoverable entity and land-claim position after origin moved by Earth delta.
        /// </summary>
        public static int RemapAll(object? excludeEntity, int originDeltaX, int originDeltaZ)
        {
            if (originDeltaX == 0 && originDeltaZ == 0)
                return 0;
            int n = 0;
            n += RemapWorldEntities(excludeEntity, originDeltaX, originDeltaZ);
            n += RemapLandClaims(originDeltaX, originDeltaZ);
            if (_logBudget > 0)
            {
                _logBudget--;
                ModApi.Log(
                    $"OriginSlideRemap: dOrigin=({originDeltaX},{originDeltaZ}) remapped≈{n} " +
                    "(entities+claims; loaded chunk columns re-injected on slide path)");
            }
            return n;
        }

        /// <summary>
        /// True when land claims exist OR claim APIs cannot be inspected (fail closed for slide).
        /// </summary>
        public static bool HasLandClaims()
        {
            try
            {
                int n = CountLandClaimBlocks(out bool inspected);
                if (!inspected)
                    return true; // fail closed: unknown claim state → refuse slide
                return n > 0;
            }
            catch
            {
                return true; // fail closed
            }
        }

        /// <returns>Claim block count; inspected=false when PPL reflection unavailable.</returns>
        static int CountLandClaimBlocks(out bool inspected)
        {
            inspected = false;
            int n = 0;
            try
            {
                object? ppl = GetPersistentPlayerList();
                if (ppl == null) return 0;
                inspected = true; // list exists (may be empty = no claims)
                // Global LP map on list if present
                n += CountCollectionField(ppl, "m_lpBlockMap", "lpBlockMap", "LPBlocks", "LandProtectionBlocks");
                foreach (var pd in EnumeratePlayerData(PlayerDataList(ppl)))
                    n += CountClaimBlocksOnPlayer(pd);
            }
            catch
            {
                inspected = false;
            }
            return n;
        }

        /// <summary>
        /// V3.0.1: GameManager.Instance.GetPersistentPlayerList() is the real API;
        /// World fallback kept for odd forks.
        /// </summary>
        static object? GetPersistentPlayerList()
        {
            try
            {
                var gmType = Type.GetType("GameManager, Assembly-CSharp");
                var inst = gmType?.GetProperty("Instance")?.GetValue(null);
                if (inst != null)
                {
                    foreach (var mn in new[] { "GetPersistentPlayerList", "GetPersistentPlayers" })
                    {
                        var m = inst.GetType().GetMethod(mn, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                        if (m != null && m.GetParameters().Length == 0)
                        {
                            var ppl = m.Invoke(inst, null);
                            if (ppl != null) return ppl;
                        }
                    }
                }
            }
            catch { /* fall through */ }

            try
            {
                object? world = ReflectCache.GetEngineWorld();
                if (world == null) return null;
                foreach (var mn in new[] { "GetPersistentPlayerList", "GetPersistentPlayers" })
                {
                    var m = world.GetType().GetMethod(mn, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    if (m != null && m.GetParameters().Length == 0)
                    {
                        var ppl = m.Invoke(world, null);
                        if (ppl != null) return ppl;
                    }
                }
                return world.GetType().GetProperty("persistentPlayers")?.GetValue(world)
                    ?? world.GetType().GetField("persistentPlayers", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(world);
            }
            catch
            {
                return null;
            }
        }

        /// <summary>Player collection off a PersistentPlayerList, falling back to the list itself.</summary>
        static object? PlayerDataList(object ppl) =>
            ppl.GetType().GetProperty("Players")?.GetValue(ppl)
            ?? ppl.GetType().GetField("Players", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(ppl)
            ?? ppl.GetType().GetProperty("Dict")?.GetValue(ppl)
            ?? ppl;

        static IEnumerable EnumeratePlayerData(object? players)
        {
            if (players == null) yield break;
            if (players is IDictionary dict)
            {
                foreach (DictionaryEntry de in dict)
                    yield return de.Value!;
                yield break;
            }
            if (players is IEnumerable en)
            {
                foreach (var item in en)
                {
                    if (item == null) continue;
                    // KeyValuePair entries → use Value
                    var t = item.GetType();
                    if (t.IsGenericType && t.Name.StartsWith("KeyValuePair", StringComparison.Ordinal))
                    {
                        var val = t.GetProperty("Value")?.GetValue(item);
                        if (val != null) yield return val;
                    }
                    else
                        yield return item;
                }
            }
        }

        static int CountCollectionField(object obj, params string[] names)
        {
            foreach (var fname in names)
            {
                var f = obj.GetType().GetField(fname, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                var p = obj.GetType().GetProperty(fname, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                object? coll = f?.GetValue(obj) ?? p?.GetValue(obj);
                if (coll is ICollection c) return c.Count;
                if (coll is IEnumerable en && coll is not string)
                {
                    int n = 0;
                    foreach (var _ in en) n++;
                    return n;
                }
            }
            return 0;
        }

        static int CountClaimBlocksOnPlayer(object? playerData)
        {
            if (playerData == null) return 0;
            return CountCollectionField(playerData,
                "LandProtectionBlocks", "LPBlocks", "landProtectionBlocks",
                "m_lpBlockMap", "lpBlockMap", "ClaimBlocks");
        }

        static int RemapWorldEntities(object? excludeEntity, int dOx, int dOz)
        {
            int n = 0;
            try
            {
                object? world = ReflectCache.GetEngineWorld();
                if (world == null) return 0;

                // World.Entities (EntityList / dictionary / list)
                var entities = world.GetType().GetProperty("Entities")?.GetValue(world)
                    ?? world.GetType().GetField("Entities", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(world);
                n += RemapEnumerableEntities(entities, excludeEntity, dOx, dOz);

                // VehicleManager.Instance vehicles
                n += RemapFromManager("VehicleManager", excludeEntity, dOx, dOz);
            }
            catch (Exception ex)
            {
                if (_logBudget > 0)
                {
                    _logBudget--;
                    ModApi.LogError("OriginSlideRemap entities: " + ex.GetType().Name + ": " + ex.Message);
                }
            }
            return n;
        }

        static int RemapFromManager(string typeName, object? exclude, int dOx, int dOz)
        {
            try
            {
                Type? t = EngineReflection.FindType(typeName);
                if (t == null) return 0;
                object? inst = t.GetProperty("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null)
                    ?? t.GetField("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null);
                if (inst == null) return 0;
                foreach (var pname in new[] { "vehicles", "Vehicles", "list", "List", "activeVehicles" })
                {
                    var p = inst.GetType().GetProperty(pname, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    var f = inst.GetType().GetField(pname, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    object? coll = p?.GetValue(inst) ?? f?.GetValue(inst);
                    int n = RemapEnumerableEntities(coll, exclude, dOx, dOz);
                    if (n > 0) return n;
                }
            }
            catch { /* ignore */ }
            return 0;
        }

        static int RemapEnumerableEntities(object? container, object? exclude, int dOx, int dOz)
        {
            if (container == null) return 0;
            int n = 0;
            try
            {
                // Dictionary values
                if (container is IDictionary dict)
                {
                    foreach (DictionaryEntry de in dict)
                    {
                        if (RemapOneEntity(de.Value, exclude, dOx, dOz))
                            n++;
                    }
                    return n;
                }

                // list / list property
                object? list = container;
                var listProp = container.GetType().GetProperty("list")
                    ?? container.GetType().GetProperty("List");
                if (listProp != null)
                    list = listProp.GetValue(container) ?? container;

                if (list is IEnumerable en)
                {
                    foreach (var e in en)
                    {
                        if (RemapOneEntity(e, exclude, dOx, dOz))
                            n++;
                    }
                }
            }
            catch { /* ignore */ }
            return n;
        }

        static bool RemapOneEntity(object? entity, object? exclude, int dOx, int dOz)
        {
            if (entity == null || ReferenceEquals(entity, exclude))
                return false;
            // Skip pure abstract / manager nodes without position
            if (!EngineReflection.TryGetPos(entity, out int x, out int y, out int z))
                return false;
            SessionOriginPolicy.RemapLocalAfterOriginDelta(x, z, dOx, dOz, out int nx, out int nz);
            if (nx == x && nz == z)
                return false;
            return EngineReflection.TrySetPos(entity, nx, y, nz);
        }

        /// <summary>
        /// Shift land-claim block positions (PersistentPlayerData land claim sets) by -dOrigin.
        /// </summary>
        static int RemapLandClaims(int dOx, int dOz)
        {
            int n = 0;
            try
            {
                object? ppl = GetPersistentPlayerList();
                if (ppl == null) return 0;
                foreach (var pd in EnumeratePlayerData(PlayerDataList(ppl)))
                    n += RemapClaimData(pd, dOx, dOz);
            }
            catch (Exception ex)
            {
                if (_logBudget > 0)
                {
                    _logBudget--;
                    ModApi.LogError("OriginSlideRemap claims: " + ex.GetType().Name + ": " + ex.Message);
                }
            }
            return n;
        }

        static int RemapClaimData(object? playerData, int dOx, int dOz)
        {
            if (playerData == null) return 0;
            int n = 0;
            try
            {
                // LandProtectionBlocks / LPBlocks / m_lpBlockMap: HashSet or Dictionary of Vector3i
                foreach (var fname in new[]
                {
                    "LandProtectionBlocks", "LPBlocks", "landProtectionBlocks",
                    "m_lpBlockMap", "lpBlockMap", "ClaimBlocks"
                })
                {
                    var f = playerData.GetType().GetField(fname, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    var p = playerData.GetType().GetProperty(fname, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    object? coll = f?.GetValue(playerData) ?? p?.GetValue(playerData);
                    if (coll == null) continue;
                    n += RemapVector3iCollection(coll, dOx, dOz);
                    if (n > 0) return n;
                }
            }
            catch { /* ignore */ }
            return n;
        }

        static int RemapVector3iCollection(object coll, int dOx, int dOz)
        {
            // Rebuild mutable collections of Vector3i-like positions.
            try
            {
                if (coll is IDictionary dict)
                {
                    // Build replacement map first; commit only when all new keys ready (no claim loss).
                    var keys = new List<object>();
                    foreach (DictionaryEntry de in dict)
                        keys.Add(de.Key!);
                    var staged = new List<(object oldKey, object newKey, object? val)>();
                    foreach (var key in keys)
                    {
                        if (!TryReadXz(key, out int x, out int y, out int z)) continue;
                        SessionOriginPolicy.RemapLocalAfterOriginDelta(x, z, dOx, dOz, out int nx, out int nz);
                        if (nx == x && nz == z) continue;
                        object? newKey = WriteXz(key, nx, y, nz);
                        if (newKey == null) continue;
                        staged.Add((key, newKey, dict[key]));
                    }
                    int n = 0;
                    foreach (var s in staged)
                    {
                        try
                        {
                            dict.Remove(s.oldKey);
                            dict[s.newKey] = s.val;
                            n++;
                        }
                        catch
                        {
                            // Restore old key if new key rejected.
                            try { dict[s.oldKey] = s.val; } catch { /* ignore */ }
                        }
                    }
                    return n;
                }

                if (coll is IList list)
                {
                    int n = 0;
                    for (int i = 0; i < list.Count; i++)
                    {
                        var item = list[i];
                        if (item == null || !TryReadXz(item, out int x, out int y, out int z)) continue;
                        SessionOriginPolicy.RemapLocalAfterOriginDelta(x, z, dOx, dOz, out int nx, out int nz);
                        if (nx == x && nz == z) continue;
                        var rewritten = WriteXz(item, nx, y, nz);
                        if (rewritten != null)
                        {
                            list[i] = rewritten;
                            n++;
                        }
                    }
                    return n;
                }

                // HashSet: copy, clear, re-add
                var clear = coll.GetType().GetMethod("Clear");
                var add = coll.GetType().GetMethod("Add");
                if (clear != null && add != null && coll is IEnumerable set)
                {
                    var items = new List<object>();
                    foreach (var it in set)
                        if (it != null) items.Add(it);
                    if (items.Count == 0) return 0;
                    clear.Invoke(coll, null);
                    int n = 0;
                    List<object>? lost = null;
                    foreach (var it in items)
                    {
                        object target = it;
                        bool moved = false;
                        if (TryReadXz(it, out int x, out int y, out int z))
                        {
                            SessionOriginPolicy.RemapLocalAfterOriginDelta(x, z, dOx, dOz, out int nx, out int nz);
                            moved = nx != x || nz != z;
                            if (moved)
                                target = WriteXz(it, nx, y, nz) ?? it;
                        }
                        // Per-item guard: the set is already cleared here, so one rejected
                        // Add must not abort the loop (the outer catch would silently drop
                        // every remaining claim). Fall back to the untouched original so the
                        // entry survives at its old position; only entries rejected in both
                        // forms are actual loss, and those are logged.
                        if (!TryAddWithFallback(add, coll, target, it))
                        {
                            (lost ??= new List<object>()).Add(it);
                            continue;
                        }
                        if (moved && !ReferenceEquals(target, it))
                            n++;
                    }
                    if (lost != null && _logBudget > 0)
                    {
                        _logBudget--;
                        ModApi.LogWarn(
                            $"OriginSlideRemap: {lost.Count}/{items.Count} land-claim entries " +
                            "could not be re-added after remap (collection rejected new and old keys)");
                    }
                    return n;
                }
            }
            catch { /* ignore */ }
            return 0;
        }

        /// <summary>
        /// Add `preferred`, falling back to `fallback` when the collection rejects it
        /// (e.g. two claims collapsing onto the same coords). False only when both
        /// forms fail: the entry is genuinely unrestorable.
        /// </summary>
        static bool TryAddWithFallback(MethodInfo add, object coll, object preferred, object fallback)
        {
            try
            {
                add.Invoke(coll, new[] { preferred });
                return true;
            }
            catch
            {
                if (ReferenceEquals(preferred, fallback))
                    return false;
                try
                {
                    add.Invoke(coll, new[] { fallback });
                    return true;
                }
                catch
                {
                    return false;
                }
            }
        }

        static bool TryReadXz(object vec, out int x, out int y, out int z)
        {
            x = y = z = 0;
            try
            {
                var t = vec.GetType();
                object? xo = t.GetField("x")?.GetValue(vec) ?? t.GetProperty("x")?.GetValue(vec);
                object? zo = t.GetField("z")?.GetValue(vec) ?? t.GetProperty("z")?.GetValue(vec);
                if (xo == null || zo == null) return false;
                object? yo = t.GetField("y")?.GetValue(vec) ?? t.GetProperty("y")?.GetValue(vec);
                x = Convert.ToInt32(xo);
                y = yo != null ? Convert.ToInt32(yo) : 0;
                z = Convert.ToInt32(zo);
                return true;
            }
            catch { return false; }
        }

        static object? WriteXz(object template, int x, int y, int z)
        {
            try
            {
                var t = template.GetType();
                // Prefer constructor (int,int,int)
                var ctor = t.GetConstructor(new[] { typeof(int), typeof(int), typeof(int) });
                if (ctor != null)
                    return ctor.Invoke(new object[] { x, y, z });
                object? clone = Activator.CreateInstance(t);
                if (clone == null) return null;
                t.GetField("x")?.SetValue(clone, x);
                t.GetField("y")?.SetValue(clone, y);
                t.GetField("z")?.SetValue(clone, z);
                t.GetProperty("x")?.SetValue(clone, x, null);
                t.GetProperty("y")?.SetValue(clone, y, null);
                t.GetProperty("z")?.SetValue(clone, z, null);
                return clone;
            }
            catch { return null; }
        }

    }
}
