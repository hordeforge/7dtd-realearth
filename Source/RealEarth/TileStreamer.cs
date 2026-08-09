using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;

namespace RealEarth
{
    /// <summary>
    /// Dynamic Earth-tile cache driven by absolute Earth block position.
    /// Does not own the host-window origin (WorldSession does); only loads .rte data
    /// for bubbles around each player so terrain inject can sample nearby.
    ///
    /// Multiplayer: overlapping per-player bubbles. Load = union of all foci;
    /// evict only tiles outside every focus unload radius (far groups keep their tiles).
    ///
    /// Hot path (inject/height sample): never blocks on disk/CDN; samples only hot tiles
    /// (fail-closed ocean until prefetch completes). Player focus path may sync-load.
    /// </summary>
    public sealed class TileStreamer
    {
        readonly string _root;
        readonly EarthCoords _coords;
        readonly RealEarthConfig _cfg;
        readonly Dictionary<long, RteTile> _hot = new Dictionary<long, RteTile>();
        /// <summary>Negative cache deadline (Environment.TickCount milliseconds).</summary>
        readonly Dictionary<long, int> _missUntilTick = new Dictionary<long, int>();
        /// <summary>In-flight disk/CDN loads.</summary>
        readonly HashSet<long> _loadInFlight = new HashSet<long>();
        /// <summary>focusId → last absolute Earth (x,z) for that player/entity.</summary>
        readonly Dictionary<int, (int x, int z)> _foci = new Dictionary<int, (int, int)>();
        readonly object _lock = new object();
        readonly HttpClient _http;

        const int MissCacheMs = 10_000;

        /// <summary>Last absolute Earth position used for streaming (primary / latest focus).</summary>
        public int FocusEarthX { get; private set; }
        public int FocusEarthZ { get; private set; }

        public int FocusCount
        {
            get { lock (_lock) return _foci.Count; }
        }

        public TileStreamer(string tileRoot, EarthCoords coords, RealEarthConfig cfg)
        {
            _root = tileRoot;
            _coords = coords;
            _cfg = cfg;
            _http = new HttpClient { Timeout = TimeSpan.FromSeconds(12) };
        }

        static long Key(int tx, int tz) => ((long)tx << 32) ^ (uint)tz;

        public string TileFilePath(int tx, int tz)
        {
            return Path.Combine(_root, "tiles", tz.ToString(), tx + ".rte");
        }

        /// <summary>
        /// Player focus update (focus id 0 = primary). Prefer the overload with a stable
        /// entity id so multiplayer keeps a union of bubbles.
        /// </summary>
        public void UpdateFromAbsolute(int earthX, int earthZ)
            => UpdateFromAbsolute(earthX, earthZ, focusId: 0, allowSyncLoad: true);

        public void UpdateFromAbsolute(int earthX, int earthZ, int focusId)
            => UpdateFromAbsolute(earthX, earthZ, focusId, allowSyncLoad: true);

        /// <summary>
        /// Multiplayer-safe: register/update one player focus and keep the union of all
        /// stream bubbles hot. Eviction is multi-center.
        /// </summary>
        public void UpdateFromAbsolute(int earthX, int earthZ, int focusId, bool allowSyncLoad)
        {
            earthX = _coords.WrapX(earthX);
            earthZ = FoldPackZ(earthZ);
            FocusEarthX = earthX;
            FocusEarthZ = earthZ;

            lock (_lock)
            {
                _foci[focusId] = (earthX, earthZ);
            }

            _coords.BlockToTile(earthX, earthZ, out int tx, out int tz);
            EnsureRadius(tx, tz, _cfg.StreamRadiusTiles, allowSyncLoad);
            EvictOutsideAllFoci(_cfg.UnloadRadiusTiles);
        }

        /// <summary>
        /// Prefetch tiles for sample without registering a player focus.
        /// Default: async only (inject/height path must not block on disk).
        /// </summary>
        public void EnsureHotAround(int earthX, int earthZ, int radius = 1)
            => EnsureHotAround(earthX, earthZ, radius, allowSyncLoad: false);

        public void EnsureHotAround(int earthX, int earthZ, int radius, bool allowSyncLoad)
        {
            earthX = _coords.WrapX(earthX);
            earthZ = FoldPackZ(earthZ);
            _coords.BlockToTile(earthX, earthZ, out int tx, out int tz);
            EnsureRadius(tx, tz, Math.Max(0, radius), allowSyncLoad);
        }

        /// <summary>Drop a focus (player left). Evicts tiles outside remaining foci; clears all if last.</summary>
        public void RemoveFocus(int focusId)
        {
            lock (_lock)
            {
                _foci.Remove(focusId);
                if (_foci.Count == 0)
                {
                    // Last player left: drop hot set (process-lifetime leak otherwise).
                    _hot.Clear();
                    return;
                }
            }
            EvictOutsideAllFoci(_cfg.UnloadRadiusTiles);
        }

        /// <summary>Tile Z into pack height so large host worlds sample pack interior.</summary>
        int FoldPackZ(int z)
        {
            int h = Math.Max(1, _coords.WorldHeight);
            if (_cfg.SingleWorldSession || _cfg.HasRegionalBbox || h <= 65536)
            {
                int r = z % h;
                return r < 0 ? r + h : r;
            }
            return _coords.ClampZ(z);
        }

        /// <summary>Back-compat alias for absolute position updates.</summary>
        public void UpdatePlayerPosition(int worldX, int worldZ) => UpdateFromAbsolute(worldX, worldZ);

        public void EnsureRadius(int centerTx, int centerTz, int radius)
            => EnsureRadius(centerTx, centerTz, radius, allowSyncLoad: false);

        public void EnsureRadius(int centerTx, int centerTz, int radius, bool allowSyncLoad)
        {
            for (int dz = -radius; dz <= radius; dz++)
            {
                for (int dx = -radius; dx <= radius; dx++)
                {
                    int tx = centerTx + dx;
                    int tz = centerTz + dz;
                    if (tz < 0 || tz >= _coords.TilesZ) continue;
                    if (_cfg.EnableLongitudeWrap)
                    {
                        int ntx = _coords.TilesX;
                        tx %= ntx;
                        if (tx < 0) tx += ntx;
                    }
                    else if (tx < 0 || tx >= _coords.TilesX) continue;

                    EnsureTile(tx, tz, allowSyncLoad);
                }
            }
        }

        public RteTile? TryGetTile(int tx, int tz)
        {
            lock (_lock)
            {
                _hot.TryGetValue(Key(tx, tz), out var t);
                return t;
            }
        }

        public bool TrySample(int worldX, int worldZ, out float elevM, out byte landcover, out byte population)
        {
            worldX = _coords.WrapX(worldX);
            worldZ = FoldPackZ(worldZ);
            _coords.BlockToTile(worldX, worldZ, out int tx, out int tz);
            var tile = TryGetTile(tx, tz);
            if (tile == null)
            {
                elevM = 0;
                landcover = 255;
                population = 0;
                return false;
            }
            int lx = worldX - tx * _coords.TileSize;
            int lz = worldZ - tz * _coords.TileSize;
            elevM = tile.ElevationAt(lx, lz);
            landcover = tile.LandcoverAt(lx, lz);
            population = tile.PopulationAt(lx, lz);
            return true;
        }

        void EnsureTile(int tx, int tz, bool allowSyncLoad)
        {
            long key = Key(tx, tz);
            lock (_lock)
            {
                if (_hot.ContainsKey(key))
                    return;
                // Miss cache is for async/query path only. Gen sync-load must retry after transient fails.
                if (!allowSyncLoad
                    && _missUntilTick.TryGetValue(key, out int until)
                    && unchecked(Environment.TickCount - until) < 0)
                    return;
            }

            var path = TileFilePath(tx, tz);
            bool exists;
            try { exists = File.Exists(path); }
            catch { exists = false; }

            if (!exists)
            {
                string? url = CdnTilePolicy.TileUrl(_cfg.TileCdnBaseUrl, tx, tz);
                if (url == null)
                {
                    MarkMiss(key);
                    return;
                }
                // Gen path: block on CDN so inject does not bake permanent ocean.
                if (allowSyncLoad)
                {
                    TryLoadCdnSync(tx, tz, path, key, url);
                    return;
                }
                QueueLoad(tx, tz, path, key, fromCdn: true);
                return;
            }

            if (allowSyncLoad)
            {
                // Wait if async already in flight; then load sync if still missing.
                if (!WaitForHotOrClaim(key, maxWaitMs: 8000))
                    return; // hot already
                TryLoadLocalSync(tx, tz, path, key);
                return;
            }

            // Height-query path: never block on ReadAllBytes + inflate.
            QueueLoad(tx, tz, path, key, fromCdn: false);
        }

        /// <summary>
        /// Returns false if tile is already hot. Otherwise waits until not in-flight (or timeout),
        /// then claims in-flight and returns true so caller can sync-load.
        /// </summary>
        bool WaitForHotOrClaim(long key, int maxWaitMs)
        {
            int start = Environment.TickCount;
            while (true)
            {
                lock (_lock)
                {
                    if (_hot.ContainsKey(key))
                        return false;
                    if (!_loadInFlight.Contains(key))
                    {
                        _loadInFlight.Add(key);
                        return true;
                    }
                }
                if (unchecked(Environment.TickCount - start) > maxWaitMs)
                {
                    // Timed out waiting; claim anyway so we can force a sync load after.
                    lock (_lock)
                    {
                        if (_hot.ContainsKey(key)) return false;
                        _loadInFlight.Add(key);
                        return true;
                    }
                }
                System.Threading.Thread.Sleep(5);
            }
        }

        void TryLoadCdnSync(int tx, int tz, string path, long key, string url)
        {
            if (!WaitForHotOrClaim(key, maxWaitMs: 12000))
                return;
            try
            {
                var bytes = _http.GetByteArrayAsync(url).ConfigureAwait(false).GetAwaiter().GetResult();
                if (bytes == null || bytes.Length < 8
                    || bytes[0] != (byte)'R' || bytes[1] != (byte)'T'
                    || bytes[2] != (byte)'E' || bytes[3] != (byte)'1')
                {
                    ModApi.Log($"CDN sync tile {tx},{tz}: bad payload");
                    MarkMiss(key);
                    lock (_lock) { _loadInFlight.Remove(key); }
                    return;
                }
                var dir = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir))
                    Directory.CreateDirectory(dir);
                PublishTileBytes(path, bytes);
                var tile = RteTile.Decode(bytes);
                lock (_lock)
                {
                    _hot[key] = tile;
                    _missUntilTick.Remove(key);
                    _loadInFlight.Remove(key);
                }
            }
            catch (Exception ex)
            {
                ModApi.Log($"CDN sync tile {tx},{tz}: {ex.Message}");
                MarkMiss(key);
                lock (_lock) { _loadInFlight.Remove(key); }
            }
        }

        /// <summary>Atomic-ish publish: unique temp + Replace so Exists never sees a delete gap.</summary>
        static void PublishTileBytes(string path, byte[] bytes)
        {
            var dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);
            string tmp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            File.WriteAllBytes(tmp, bytes);
            try
            {
                if (File.Exists(path))
                {
                    // Replace is atomic on most platforms when destination exists.
                    File.Replace(tmp, path, null);
                }
                else
                {
                    File.Move(tmp, path);
                }
            }
            catch
            {
                try
                {
                    if (File.Exists(path))
                        File.Delete(path);
                    File.Move(tmp, path);
                }
                catch
                {
                    try { if (File.Exists(tmp)) File.Delete(tmp); } catch { /* ignore */ }
                    throw;
                }
            }
        }

        void QueueLoad(int tx, int tz, string path, long key, bool fromCdn)
        {
            bool start;
            lock (_lock)
            {
                if (_hot.ContainsKey(key)) return;
                start = _loadInFlight.Add(key);
            }
            if (!start) return;
            _ = LoadTileFireAndForget(tx, tz, path, key, fromCdn);
        }

        void TryLoadLocalSync(int tx, int tz, string path, long key)
        {
            try
            {
                var tile = RteTile.Load(path);
                lock (_lock)
                {
                    _hot[key] = tile;
                    _missUntilTick.Remove(key);
                    _loadInFlight.Remove(key);
                }
            }
            catch (Exception ex)
            {
                ModApi.Log($"Load tile {tx},{tz}: {ex.Message}");
                MarkMiss(key);
                lock (_lock) { _loadInFlight.Remove(key); }
            }
        }

        void MarkMiss(long key)
        {
            lock (_lock)
            {
                _missUntilTick[key] = Environment.TickCount + MissCacheMs;
            }
        }

        async Task LoadTileFireAndForget(int tx, int tz, string path, long key, bool fromCdn)
        {
            try
            {
                byte[] bytes;
                if (fromCdn)
                {
                    string? url = CdnTilePolicy.TileUrl(_cfg.TileCdnBaseUrl, tx, tz);
                    if (url == null)
                    {
                        MarkMiss(key);
                        return;
                    }
                    bytes = await _http.GetByteArrayAsync(url).ConfigureAwait(false);
                    if (bytes == null || bytes.Length < 8
                        || bytes[0] != (byte)'R' || bytes[1] != (byte)'T'
                        || bytes[2] != (byte)'E' || bytes[3] != (byte)'1')
                    {
                        ModApi.Log($"CDN tile {tx},{tz}: bad payload (not RTE1)");
                        MarkMiss(key);
                        return;
                    }
                    PublishTileBytes(path, bytes);
                }
                else
                {
                    // Disk decode off inject thread.
                    bytes = await Task.Run(() => File.ReadAllBytes(path)).ConfigureAwait(false);
                }

                var tile = RteTile.Decode(bytes);
                lock (_lock)
                {
                    _hot[key] = tile;
                    _missUntilTick.Remove(key);
                }
            }
            catch (Exception ex)
            {
                if (fromCdn)
                {
                    ModApi.Log(
                        $"CDN tile {tx},{tz} failed (failClosed={CdnTilePolicy.FailClosedOnMiss(_cfg.FailClosedMissingTiles)}): {ex.Message}");
                }
                else
                {
                    ModApi.Log($"Async load tile {tx},{tz}: {ex.Message}");
                }
                MarkMiss(key);
            }
            finally
            {
                lock (_lock)
                {
                    _loadInFlight.Remove(key);
                }
            }
        }

        /// <summary>
        /// Remove tiles that are outside the unload radius of every registered focus.
        /// Overlapping and far-apart multiplayer groups both keep their hot sets.
        /// </summary>
        void EvictOutsideAllFoci(int keepRadius)
        {
            List<(int tx, int tz)> centers;
            lock (_lock)
            {
                if (_foci.Count == 0)
                {
                    _hot.Clear();
                    return;
                }
                centers = new List<(int, int)>(_foci.Count);
                foreach (var kv in _foci)
                {
                    _coords.BlockToTile(kv.Value.x, kv.Value.z, out int tx, out int tz);
                    centers.Add((tx, tz));
                }
            }

            lock (_lock)
            {
                var remove = new List<long>();
                foreach (var kv in _hot)
                {
                    int tx = (int)(kv.Key >> 32);
                    int tz = (int)(kv.Key & 0xffffffff);
                    if (!IsWithinAnyFocus(tx, tz, centers, keepRadius))
                        remove.Add(kv.Key);
                }
                foreach (var k in remove)
                    _hot.Remove(k);
            }
        }

        bool IsWithinAnyFocus(int tx, int tz, List<(int tx, int tz)> centers, int keepRadius)
        {
            foreach (var c in centers)
            {
                int dx = Math.Abs(tx - c.tx);
                int dz = Math.Abs(tz - c.tz);
                if (_cfg.EnableLongitudeWrap)
                {
                    int ntx = _coords.TilesX;
                    if (ntx > 0)
                        dx = Math.Min(dx, ntx - dx);
                }
                if (dx <= keepRadius && dz <= keepRadius)
                    return true;
            }
            return false;
        }

        public int HotTileCount
        {
            get { lock (_lock) return _hot.Count; }
        }

        /// <summary>Drop all hot tiles and miss deadlines (e.g. after origin slide).</summary>
        public void InvalidateHotCache()
        {
            lock (_lock)
            {
                _hot.Clear();
                _missUntilTick.Clear();
            }
        }
    }
}
