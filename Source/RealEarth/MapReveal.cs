using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// Debug FOW: uncover a wide area of the in-game map (not only visited chunks).
    /// Uses GameManager.fowDatabaseForLocalPlayer / MapChunkDatabase.Add.
    /// </summary>
    public static class MapReveal
    {
        static bool _fullDone;
        static int _fullRetryBudget = 24;
        static int _radiusCooldown;
        static int _lastCx = int.MinValue;
        static int _lastCz = int.MinValue;

        public static void TryRevealIfConfigured()
        {
            TryRevealIfConfigured(null, null);
        }

        /// <param name="playerLocalX">Engine block X of local player (optional; enables radius reveal).</param>
        /// <param name="playerLocalZ">Engine block Z of local player.</param>
        public static void TryRevealIfConfigured(int? playerLocalX, int? playerLocalZ)
        {
            var cfg = ModApi.Config;
            if (cfg == null)
                return;
            if (!cfg.DebugRevealFullMap && cfg.DebugMapRevealRadiusChunks <= 0)
                return;

            try
            {
                RaiseUncoveredChunkCap();

                if (cfg.DebugRevealFullMap && !_fullDone)
                {
                    if (RevealFullMap())
                    {
                        _fullDone = true;
                        ModApi.Log("DebugRevealFullMap: host map FOW filled.");
                    }
                    else if (_fullRetryBudget-- <= 0)
                    {
                        _fullDone = true;
                        ModApi.Log("DebugRevealFullMap: gave up (no FOW database yet).");
                    }
                }

                int radius = Math.Max(0, cfg.DebugMapRevealRadiusChunks);
                if (radius > 0 && playerLocalX.HasValue && playerLocalZ.HasValue)
                    RevealRadiusAroundPlayer(playerLocalX.Value, playerLocalZ.Value, radius);
            }
            catch (Exception ex)
            {
                ModApi.Log($"MapReveal failed: {ex.Message}");
                _fullDone = true;
            }
        }

        /// <summary>Force re-run (world change / console).</summary>
        public static void Reset()
        {
            _fullDone = false;
            _fullRetryBudget = 24;
            _radiusCooldown = 0;
            _lastCx = int.MinValue;
            _lastCz = int.MinValue;
        }

        public static bool RevealFullMap()
        {
            if (!TryGetFowAdd(out object fow, out MethodInfo add))
                return false;

            if (!TryGetWorldChunkBounds(out int minCx, out int minCz, out int maxCx, out int maxCz))
            {
                int half = Math.Max(32, ModApi.Config.LocalWindowSize / 16);
                minCx = -half;
                minCz = -half;
                maxCx = half;
                maxCz = half;
            }

            return AddRect(fow, add, minCx, minCz, maxCx, maxCz, "full");
        }

        public static bool RevealRadiusAroundPlayer(int localBlockX, int localBlockZ, int radiusChunks)
        {
            if (radiusChunks <= 0)
                return false;
            if (_radiusCooldown > 0)
            {
                _radiusCooldown--;
                return true;
            }

            int cx = FloorDiv(localBlockX, 16);
            int cz = FloorDiv(localBlockZ, 16);
            // Re-fill when player moved ≥ 8 chunks or every ~2s of ticks after cooldown
            if (Math.Abs(cx - _lastCx) < 8 && Math.Abs(cz - _lastCz) < 8 && _lastCx != int.MinValue)
            {
                _radiusCooldown = 30;
                return true;
            }

            if (!TryGetFowAdd(out object fow, out MethodInfo add))
                return false;

            int minCx = cx - radiusChunks;
            int maxCx = cx + radiusChunks;
            int minCz = cz - radiusChunks;
            int maxCz = cz + radiusChunks;
            bool ok = AddRect(fow, add, minCx, minCz, maxCx, maxCz, "radius");
            if (ok)
            {
                _lastCx = cx;
                _lastCz = cz;
                _radiusCooldown = 45; // throttle
            }
            return ok;
        }

        static bool AddRect(
            object fow,
            MethodInfo add,
            int minCx,
            int minCz,
            int maxCx,
            int maxCz,
            string tag)
        {
            int mapSize = ReadMapChunkSize();
            int pixels = mapSize * mapSize;
            if (pixels <= 0 || pixels > 65536)
            {
                mapSize = 16;
                pixels = 256;
            }

            int total = (maxCx - minCx + 1) * (maxCz - minCz + 1);
            const int maxChunks = 200_000;
            if (total > maxChunks)
            {
                int midX = (minCx + maxCx) / 2;
                int midZ = (minCz + maxCz) / 2;
                int r = (int)(Math.Sqrt(maxChunks) / 2);
                minCx = midX - r;
                maxCx = midX + r;
                minCz = midZ - r;
                maxCz = midZ + r;
                total = (maxCx - minCx + 1) * (maxCz - minCz + 1);
                ModApi.Log($"MapReveal[{tag}]: clamped to {total} chunks around center.");
            }

            int added = 0;
            // Fresh buffer per chunk: MapChunkDatabase.Add may store the array reference.
            for (int cz = minCz; cz <= maxCz; cz++)
            {
                for (int cx = minCx; cx <= maxCx; cx++)
                {
                    var piece = new ushort[pixels];
                    FillMapPiece(piece, mapSize, cx, cz);
                    if (TryAdd(add, fow, cx, cz, piece))
                        added++;
                }
            }

            if (added > 0 && (tag == "full" || added >= 100))
            {
                ModApi.Log(
                    $"MapReveal[{tag}]: added {added}/{total} map chunks " +
                    $"cx[{minCx},{maxCx}] cz[{minCz},{maxCz}]");
            }
            return added > 0;
        }

        static bool TryAdd(MethodInfo add, object fow, int cx, int cz, ushort[] piece)
        {
            try
            {
                add.Invoke(fow, new object[] { cx, cz, piece });
                return true;
            }
            catch
            {
                try
                {
                    var copy = new ushort[piece.Length];
                    Array.Copy(piece, copy, piece.Length);
                    add.Invoke(fow, new object[] { cx, cz, copy });
                    return true;
                }
                catch
                {
                    return false;
                }
            }
        }

        static bool TryGetFowAdd(out object fow, out MethodInfo add)
        {
            fow = GetFowDatabase()!;
            add = null!;
            if (fow == null)
                return false;
            var m = FindAdd(fow.GetType());
            if (m == null)
            {
                ModApi.Log("MapReveal: MapChunkDatabase.Add(int,int,ushort[]) not found.");
                return false;
            }
            add = m;
            return true;
        }

        static void FillMapPiece(ushort[] piece, int mapSize, int chunkX, int chunkZ)
        {
            int blockOriginX = chunkX * 16;
            int blockOriginZ = chunkZ * 16;
            byte h = ChunkTerrainSampler.SampleGameHeight(blockOriginX + 8, blockOriginZ + 8);
            byte lc = ChunkTerrainSampler.SampleLandcover(blockOriginX + 8, blockOriginZ + 8);
            ushort color = LandcoverToMapColor(lc, h);
            for (int i = 0; i < piece.Length; i++)
                piece[i] = color;

            if (mapSize >= 4)
            {
                for (int z = 0; z < mapSize; z++)
                {
                    for (int x = 0; x < mapSize; x++)
                    {
                        int wx = blockOriginX + x * 16 / mapSize;
                        int wz = blockOriginZ + z * 16 / mapSize;
                        byte hh = ChunkTerrainSampler.SampleGameHeight(wx, wz);
                        byte llc = ChunkTerrainSampler.SampleLandcover(wx, wz);
                        piece[z * mapSize + x] = LandcoverToMapColor(llc, hh);
                    }
                }
            }
        }

        public static ushort PackRgb565(int r, int g, int b)
        {
            r = Math.Max(0, Math.Min(255, r));
            g = Math.Max(0, Math.Min(255, g));
            b = Math.Max(0, Math.Min(255, b));
            return (ushort)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
        }

        public static ushort LandcoverToMapColor(byte lc, byte height)
        {
            int lift = Math.Min(40, height / 4);
            switch (lc)
            {
                case 0:
                case 1:
                    return PackRgb565(20, 40 + lift / 2, 120 + lift);
                case 2:
                case 10:
                    return PackRgb565(220, 220, 230);
                case 3:
                    return PackRgb565(140 + lift, 100, 40);
                case 5:
                case 11:
                    return PackRgb565(200 + lift / 2, 180, 80);
                case 9:
                    return PackRgb565(90, 90, 90 + lift);
                default:
                    return PackRgb565(30, 90 + lift, 30);
            }
        }

        static void RaiseUncoveredChunkCap()
        {
            try
            {
                Type? prefs = FindType("GamePrefs");
                Type? enumType = FindType("EnumGamePrefs");
                if (prefs == null || enumType == null) return;
                object? key = Enum.Parse(enumType, "MaxUncoveredMapChunksPerPlayer");
                MethodInfo? set = null;
                foreach (var m in prefs.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
                {
                    if (m.Name != "Set") continue;
                    var ps = m.GetParameters();
                    if (ps.Length == 2 && ps[0].ParameterType == enumType)
                    {
                        set = m;
                        break;
                    }
                }
                if (set == null) return;
                object val = 1_000_000;
                if (set.GetParameters()[1].ParameterType == typeof(int))
                    set.Invoke(null, new[] { key, val });
                else
                    set.Invoke(null, new[] { key, Convert.ChangeType(val, set.GetParameters()[1].ParameterType) });
            }
            catch
            {
                // optional
            }
        }

        static object? GetFowDatabase()
        {
            try
            {
                Type? gmType = FindType("GameManager");
                if (gmType == null) return null;
                object? inst = gmType.GetProperty("Instance", BindingFlags.Static | BindingFlags.Public)?.GetValue(null)
                    ?? gmType.GetField("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null);
                if (inst == null) return null;

                var f = gmType.GetField("fowDatabaseForLocalPlayer",
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (f != null)
                {
                    var db = f.GetValue(inst);
                    if (db != null) return db;
                }

                var world = gmType.GetProperty("World")?.GetValue(inst)
                    ?? gmType.GetField("m_World", BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(inst);
                if (world == null) return null;
                foreach (var name in new[] { "GetPrimaryPlayer", "GetLocalPlayers" })
                {
                    var m = world.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    if (m == null) continue;
                    var p = m.GetParameters();
                    object? player = p.Length == 0 ? m.Invoke(world, null) : null;
                    if (player is System.Collections.IEnumerable en && name.Contains("Local"))
                    {
                        foreach (var pl in en)
                        {
                            var db = ExtractMapDatabase(pl);
                            if (db != null) return db;
                        }
                    }
                    else if (player != null)
                    {
                        var db = ExtractMapDatabase(player);
                        if (db != null) return db;
                    }
                }
            }
            catch
            {
                // ignore
            }
            return null;
        }

        static object? ExtractMapDatabase(object player)
        {
            foreach (var fi in player.GetType().GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (fi.Name.IndexOf("mapDatabase", StringComparison.OrdinalIgnoreCase) >= 0
                    || fi.Name.IndexOf("MapDatabase", StringComparison.OrdinalIgnoreCase) >= 0
                    || fi.Name.IndexOf("fow", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    var v = fi.GetValue(player);
                    if (v != null && v.GetType().Name.IndexOf("MapChunk", StringComparison.OrdinalIgnoreCase) >= 0)
                        return v;
                }
                if (fi.FieldType.Name.IndexOf("ChunkObserver", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    var obs = fi.GetValue(player);
                    if (obs == null) continue;
                    var mf = obs.GetType().GetField("mapDatabase", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    var db = mf?.GetValue(obs);
                    if (db != null) return db;
                }
            }
            return null;
        }

        static MethodInfo? FindAdd(Type dbType)
        {
            foreach (var m in dbType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (m.Name != "Add") continue;
                var ps = m.GetParameters();
                if (ps.Length == 3
                    && ps[0].ParameterType == typeof(int)
                    && ps[1].ParameterType == typeof(int)
                    && ps[2].ParameterType == typeof(ushort[]))
                    return m;
            }
            foreach (var iface in dbType.GetInterfaces())
            {
                var m = FindAdd(iface);
                if (m != null) return m;
            }
            return null;
        }

        static bool TryGetWorldChunkBounds(out int minCx, out int minCz, out int maxCx, out int maxCz)
        {
            minCx = minCz = maxCx = maxCz = 0;
            try
            {
                Type? gmType = FindType("GameManager");
                object? inst = gmType?.GetProperty("Instance", BindingFlags.Static | BindingFlags.Public)?.GetValue(null);
                object? world = gmType?.GetProperty("World")?.GetValue(inst);
                if (world == null) return false;

                object? provider = world.GetType().GetProperty("ChunkCache")?.GetValue(world)
                    ?? world.GetType().GetField("m_ChunkCache", BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(world);
                object? cp = provider?.GetType().GetProperty("ChunkProvider")?.GetValue(provider)
                    ?? world.GetType().GetProperty("ChunkProvider")?.GetValue(world);

                MethodInfo? extent = null;
                object? target = cp ?? world;
                foreach (var m in target.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                {
                    if (m.Name != "GetWorldExtent") continue;
                    if (m.GetParameters().Length == 2)
                    {
                        extent = m;
                        break;
                    }
                }
                if (extent == null) return false;

                var args = new object?[] { null, null };
                var ps = extent.GetParameters();
                args[0] = Activator.CreateInstance(ps[0].ParameterType.IsByRef
                    ? ps[0].ParameterType.GetElementType()!
                    : ps[0].ParameterType);
                args[1] = Activator.CreateInstance(ps[1].ParameterType.IsByRef
                    ? ps[1].ParameterType.GetElementType()!
                    : ps[1].ParameterType);
                object? ok = extent.Invoke(target, args);
                if (ok is bool b && !b) return false;

                ReadVec3i(args[0]!, out int minX, out _, out int minZ);
                ReadVec3i(args[1]!, out int maxX, out _, out int maxZ);
                minCx = FloorDiv(minX, 16);
                minCz = FloorDiv(minZ, 16);
                maxCx = FloorDiv(maxX, 16);
                maxCz = FloorDiv(maxZ, 16);
                if (maxCx < minCx) (minCx, maxCx) = (maxCx, minCx);
                if (maxCz < minCz) (minCz, maxCz) = (maxCz, minCz);
                return maxCx > minCx || maxCz > minCz || (maxX != 0 || maxZ != 0);
            }
            catch
            {
                return false;
            }
        }

        static void ReadVec3i(object v, out int x, out int y, out int z)
        {
            x = y = z = 0;
            var t = v.GetType();
            x = Convert.ToInt32(t.GetField("x")?.GetValue(v) ?? t.GetProperty("x")?.GetValue(v, null) ?? 0);
            y = Convert.ToInt32(t.GetField("y")?.GetValue(v) ?? t.GetProperty("y")?.GetValue(v, null) ?? 0);
            z = Convert.ToInt32(t.GetField("z")?.GetValue(v) ?? t.GetProperty("z")?.GetValue(v, null) ?? 0);
        }

        static int FloorDiv(int a, int b)
        {
            if (a >= 0) return a / b;
            return (a - (b - 1)) / b;
        }

        static int ReadMapChunkSize()
        {
            try
            {
                Type? t = FindType("MapChunkDatabase");
                var f = t?.GetField("MapChunkSize", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
                        ?? FindType("Constants")?.GetField("MapChunkSize", BindingFlags.Static | BindingFlags.Public);
                if (f == null)
                {
                    foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                    {
                        if (!string.Equals(asm.GetName().Name, "Assembly-CSharp", StringComparison.OrdinalIgnoreCase))
                            continue;
                        foreach (var ty in SafeGetTypes(asm))
                        {
                            f = ty.GetField("MapChunkSize", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                            if (f != null && f.FieldType == typeof(int))
                                break;
                        }
                    }
                }
                if (f != null)
                    return Convert.ToInt32(f.GetValue(null));
            }
            catch { /* default */ }
            return 16;
        }

        static IEnumerable<Type> SafeGetTypes(Assembly asm)
        {
            try { return asm.GetTypes(); }
            catch (ReflectionTypeLoadException ex)
            {
                return (ex.Types ?? Array.Empty<Type>()).Where(t => t != null)!;
            }
        }

        static Type? FindType(string name)
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    var t = asm.GetType(name, false);
                    if (t != null) return t;
                    foreach (var ty in SafeGetTypes(asm))
                        if (ty.Name == name) return ty;
                }
                catch { /* ignore */ }
            }
            return null;
        }
    }
}
