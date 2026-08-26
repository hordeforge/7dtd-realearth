using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;

namespace RealEarth
{
    /// <summary>
    /// Debug FOW: uncover a wide area of the in-game map (not only visited chunks).
    /// Uses GameManager.fowDatabaseForLocalPlayer / MapChunkDatabase.Add.
    /// </summary>
    public static class MapReveal
    {
        // Reveal state is cross-thread: TryRevealIfConfigured runs on the main thread
        // (player tick / world ready) while `rereveal` (console/telnet) resets and
        // re-runs it off-thread, so budgets and done-flags use Interlocked/Volatile
        // instead of plain read-modify-write. _lastCx/_lastCz stay plain ints:
        // atomic writes, advisory throttle inputs where a stale read is harmless.
        static int _fullDone; // 0 = pending, 1 = done or gave up
        static int _fullRetryBudget = 24;
        static int _radiusCooldown;
        static int _lastCx = int.MinValue;
        static int _lastCz = int.MinValue;
        /// <summary>GamePrefs cap raised at most once per process (per-tick re-raise is pure overhead).</summary>
        static int _uncoveredCapRaised; // 0 = not raised, 1 = raised

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

                if (cfg.DebugRevealFullMap && Volatile.Read(ref _fullDone) == 0)
                {
                    if (RevealFullMap())
                    {
                        Volatile.Write(ref _fullDone, 1);
                        ModApi.Log("DebugRevealFullMap: host map FOW filled.");
                    }
                    else if (Interlocked.Decrement(ref _fullRetryBudget) < 0)
                    {
                        Volatile.Write(ref _fullDone, 1);
                        ModApi.Log("DebugRevealFullMap: gave up (no FOW database yet).");
                    }
                }

                int radius = Math.Max(0, cfg.DebugMapRevealRadiusChunks);
                if (radius > 0 && playerLocalX.HasValue && playerLocalZ.HasValue)
                    RevealRadiusAroundPlayer(playerLocalX.Value, playerLocalZ.Value, radius);
            }
            catch (Exception ex)
            {
                ModApi.LogError($"MapReveal failed: {ex.Message}");
                Volatile.Write(ref _fullDone, 1);
            }
        }

        /// <summary>Force re-run (world change / console).</summary>
        public static void Reset()
        {
            Volatile.Write(ref _fullDone, 0);
            Volatile.Write(ref _fullRetryBudget, 24);
            Volatile.Write(ref _radiusCooldown, 0);
            _lastCx = int.MinValue;
            _lastCz = int.MinValue;
            Volatile.Write(ref _uncoveredCapRaised, 0);
        }

        public static bool RevealFullMap()
        {
            if (!TryGetFowAdd(out object? fow, out MethodInfo? add)
                || fow == null || add == null)
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
            if (Volatile.Read(ref _radiusCooldown) > 0)
            {
                Interlocked.Decrement(ref _radiusCooldown);
                return true;
            }

            int cx = EngineReflection.FloorDiv(localBlockX, 16);
            int cz = EngineReflection.FloorDiv(localBlockZ, 16);
            // Re-fill when player moved ≥ 8 chunks or every ~2s of ticks after cooldown
            if (Math.Abs(cx - _lastCx) < 8 && Math.Abs(cz - _lastCz) < 8 && _lastCx != int.MinValue)
            {
                Volatile.Write(ref _radiusCooldown, 30);
                return true;
            }

            if (!TryGetFowAdd(out object? fow, out MethodInfo? add)
                || fow == null || add == null)
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
                Volatile.Write(ref _radiusCooldown, 45); // throttle
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

        static bool TryGetFowAdd(out object? fow, out MethodInfo? add)
        {
            fow = GetFowDatabase();
            if (fow == null)
            {
                add = null;
                return false;
            }
            var m = FindAdd(fow.GetType());
            if (m == null)
            {
                ModApi.LogWarn("MapReveal: MapChunkDatabase.Add(int,int,ushort[]) not found.");
                add = null;
                return false;
            }
            add = m;
            return true;
        }

        static void FillMapPiece(ushort[] piece, int mapSize, int chunkX, int chunkZ)
        {
            var session = ModApi.Session;
            var streamer = ModApi.Streamer;
            var cfg = ModApi.Config;
            int blockOriginX = chunkX * 16;
            int blockOriginZ = chunkZ * 16;

            if (mapSize >= 4)
            {
                // piece.Length == mapSize*mapSize, so this loop paints every cell;
                // the fused sample keeps one locked lookup per pixel instead of two.
                for (int z = 0; z < mapSize; z++)
                {
                    for (int x = 0; x < mapSize; x++)
                    {
                        int wx = blockOriginX + x * 16 / mapSize;
                        int wz = blockOriginZ + z * 16 / mapSize;
                        byte hh = ChunkTerrainSampler.SampleColumnByte(
                            session, streamer, cfg, wx, wz, out byte llc);
                        piece[z * mapSize + x] = LandcoverToMapColor(llc, hh);
                    }
                }
                return;
            }

            // Coarser than the pixel grid: flat center-sample color everywhere.
            byte h = ChunkTerrainSampler.SampleColumnByte(
                session, streamer, cfg, blockOriginX + 8, blockOriginZ + 8, out byte lc);
            ushort color = LandcoverToMapColor(lc, h);
            for (int i = 0; i < piece.Length; i++)
                piece[i] = color;
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
            if (Volatile.Read(ref _uncoveredCapRaised) != 0) return;
            try
            {
                Type? prefs = EngineReflection.FindType("GamePrefs");
                Type? enumType = EngineReflection.FindType("EnumGamePrefs");
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
                Volatile.Write(ref _uncoveredCapRaised, 1);
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
                Type? gmType = EngineReflection.FindType("GameManager");
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
                Type? gmType = EngineReflection.FindType("GameManager");
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
                minCx = EngineReflection.FloorDiv(minX, 16);
                minCz = EngineReflection.FloorDiv(minZ, 16);
                maxCx = EngineReflection.FloorDiv(maxX, 16);
                maxCz = EngineReflection.FloorDiv(maxZ, 16);
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

        static int ReadMapChunkSize()
        {
            try
            {
                Type? t = EngineReflection.FindType("MapChunkDatabase");
                var f = t?.GetField("MapChunkSize", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
                        ?? EngineReflection.FindType("Constants")?.GetField("MapChunkSize", BindingFlags.Static | BindingFlags.Public);
                if (f == null)
                {
                    foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                    {
                        if (!string.Equals(asm.GetName().Name, "Assembly-CSharp", StringComparison.OrdinalIgnoreCase))
                            continue;
                        foreach (var ty in EngineReflection.SafeGetTypes(asm))
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
    }
}
