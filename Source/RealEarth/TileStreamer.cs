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
        /// <summary>focusId → last absolute Earth (x,z), streamed tile, and last-update tick.</summary>
        readonly Dictionary<int, (int x, int z, int tx, int tz, int tick)> _foci =
            new Dictionary<int, (int, int, int, int, int)>();
        readonly object _lock = new object();
        readonly HttpClient _http;

        const int MissCacheMs = 10_000;
        /// <summary>
        /// Deadline for the streamed CDN body copy (matches the HttpClient header
        /// timeout; see FetchTileBytesAsync for why the body needs its own bound).
        /// </summary>
        static readonly TimeSpan BodyReadTimeout = TimeSpan.FromSeconds(12);
        /// <summary>
        /// A focus silent this long belongs to an entity whose unload postfix never ran
        /// (the EntityPlayer OnEntityUnload/Despawn/Kill bind is best-effort reflection;
        /// a game update that renames those methods would otherwise pin every departed
        /// player's bubble tiles hot forever). Live entities refresh their focus every
        /// tick, so the TTL only ever fires on despawned/drifted ids.
        /// </summary>
        internal const int FocusStaleMs = 600_000;
        /// <summary>
        /// Negative-cache entries allowed before expired deadlines are swept. Without this,
        /// one entry per failed tile lives for the whole server uptime (map only grows).
        /// </summary>
        const int MissCachePruneThreshold = 4096;

        /// <summary>
        /// Cap on CDN tile payloads (a full 512x512 .rte is well under 2 MB). Bounds memory
        /// when the configured CDN misbehaves or turns hostile.
        /// </summary>
        internal const long MaxCdnTileBytes = 64L * 1024L * 1024L;

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

        /// <summary>Shared miss result: ocean-flat placeholder, landcover 255 = unknown.</summary>
        static void MissSample(out float elevM, out byte landcover, out byte population)
        {
            elevM = 0;
            landcover = 255;
            population = 0;
        }

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

            _coords.BlockToTile(earthX, earthZ, out int tx, out int tz);

            // Per-tick path: focus updates arrive every tick per player. When the focus
            // is still inside the same tile the radius scan and multi-center eviction
            // cannot change anything (this focus's tiles are never evicted while it is a
            // registered center), so skip both instead of re-walking every hot tile
            // under the lock the height-sample hot path shares.
            int now = Environment.TickCount;
            bool droppedStale;
            lock (_lock)
            {
                droppedStale = SweepStaleFociLocked(now);
                if (!droppedStale
                    && _foci.TryGetValue(focusId, out var prev)
                    && prev.tx == tx && prev.tz == tz)
                {
                    // Same-tile fast path (rationale above): still refresh the
                    // heartbeat so an idle-but-connected player is never swept.
                    _foci[focusId] = (earthX, earthZ, tx, tz, now);
                    return;
                }
                _foci[focusId] = (earthX, earthZ, tx, tz, now);
            }

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

        /// <summary>
        /// Bound on the focus map when unload postfixes never bound. Caller holds _lock.
        /// Returns true when any stale focus was dropped (caller must then run eviction
        /// so that player's bubble tiles can leave the hot set).
        /// </summary>
        bool SweepStaleFociLocked(int now)
        {
            if (_foci.Count == 0)
                return false;
            List<int>? stale = null;
            foreach (var kv in _foci)
            {
                // Same wrap-safe delta as the miss cache readers.
                if (unchecked(now - kv.Value.tick) >= FocusStaleMs)
                    (stale ??= new List<int>()).Add(kv.Key);
            }
            if (stale == null)
                return false;
            foreach (int id in stale)
                _foci.Remove(id);
            return true;
        }

        /// <summary>
        /// Tile Z into pack height so large host worlds sample pack interior.
        /// Mirrors WorldSession.FoldZ via the same SessionOriginPolicy predicate, so the
        /// streamer and the session mapping can never disagree on out-of-pack Z.
        /// </summary>
        int FoldPackZ(int z)
        {
            if (SessionOriginPolicy.ShouldFoldHostIntoPack(
                    _cfg.SingleWorldSession, _cfg.HasRegionalBbox,
                    _coords.WorldWidth, _coords.WorldHeight)
                && !_cfg.EnableLongitudeWrap)
            {
                return SessionOriginPolicy.FoldCoord(z, _coords.WorldHeight);
            }
            return _coords.ClampZ(z);
        }

        public void EnsureRadius(int centerTx, int centerTz, int radius)
            => EnsureRadius(centerTx, centerTz, radius, allowSyncLoad: false);

        public void EnsureRadius(int centerTx, int centerTz, int radius, bool allowSyncLoad)
        {
            // Hot path (per block sample / player tick): one lock pass filters already-hot
            // and miss-cached tiles; only genuine misses go through EnsureTile.
            List<long>? missing = null;
            int now = Environment.TickCount;
            lock (_lock)
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

                        long key = Key(tx, tz);
                        if (_hot.ContainsKey(key)) continue;
                        if (!allowSyncLoad
                            && _missUntilTick.TryGetValue(key, out int until)
                            && unchecked(now - until) < 0) continue;
                        (missing ??= new List<long>()).Add(key);
                    }
                }
            }
            if (missing == null) return;
            foreach (long key in missing)
            {
                int tx = (int)(key >> 32);
                int tz = (int)(key & 0xffffffff);
                EnsureTile(tx, tz, allowSyncLoad);
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

        /// <summary>
        /// Hot-path sample for per-block height/landcover queries: one lock pass returns
        /// the center-tile sample when hot. On a miss it falls back to the async radius-1
        /// prefetch (negative-cache aware, never focus-registering), identical load
        /// behavior to EnsureHotAround+TrySample at half the lock traffic and without the
        /// 9-tile scan when the tile is already hot.
        /// </summary>
        public bool TrySamplePrefetch(int worldX, int worldZ, out float elevM, out byte landcover, out byte population)
        {
            worldX = _coords.WrapX(worldX);
            worldZ = FoldPackZ(worldZ);
            _coords.BlockToTile(worldX, worldZ, out int tx, out int tz);
            long key = Key(tx, tz);
            RteTile? tile;
            lock (_lock)
            {
                if (_hot.TryGetValue(key, out tile))
                {
                    int lx = worldX - tx * _coords.TileSize;
                    int lz = worldZ - tz * _coords.TileSize;
                    elevM = tile.ElevationAt(lx, lz);
                    landcover = tile.LandcoverAt(lx, lz);
                    population = tile.PopulationAt(lx, lz);
                    return true;
                }
                // Same negative-cache filter as EnsureRadius: do not re-queue within deadline.
                int now = Environment.TickCount;
                if (_missUntilTick.TryGetValue(key, out int until)
                    && unchecked(now - until) < 0)
                {
                    MissSample(out elevM, out landcover, out population);
                    return false;
                }
            }
            EnsureRadius(tx, tz, 1, allowSyncLoad: false);
            MissSample(out elevM, out landcover, out population);
            return false;
        }

        public bool TrySample(int worldX, int worldZ, out float elevM, out byte landcover, out byte population)
        {
            worldX = _coords.WrapX(worldX);
            worldZ = FoldPackZ(worldZ);
            _coords.BlockToTile(worldX, worldZ, out int tx, out int tz);
            var tile = TryGetTile(tx, tz);
            if (tile == null)
            {
                MissSample(out elevM, out landcover, out population);
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
                var bytes = FetchTileBytesAsync(url).ConfigureAwait(false).GetAwaiter().GetResult();
                if (bytes == null || bytes.Length < 8 || !RteTile.HasMagic(bytes))
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

        /// <summary>
        /// Durable publish via shared AtomicPublish (unique temp + Replace,
        /// backup-move fallback that never drops the live file before its
        /// replacement is secured).
        /// </summary>
        static void PublishTileBytes(string path, byte[] bytes)
            => AtomicPublish.WriteAllBytes(path, bytes);

        /// <summary>
        /// GET a tile with a hard size cap (headers first, then streamed read) so a
        /// hostile CDN cannot buffer an unbounded response before validation.
        /// The streamed copy carries its own deadline: HttpClient.Timeout stops at
        /// the response headers under ResponseHeadersRead (net48), so without this a
        /// CDN that accepts the request and then stalls would block the sync gen
        /// path indefinitely.
        /// </summary>
        async Task<byte[]> FetchTileBytesAsync(string url)
        {
            if (!CdnTilePolicy.IsSafeTileUrl(url))
                throw new InvalidDataException("tile URL must be https");
            using var resp = await _http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead).ConfigureAwait(false);
            // Defense-in-depth: reject redirects that downgrade to http (HttpClient follows by default).
            if (resp.RequestMessage?.RequestUri != null && !resp.RequestMessage.RequestUri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("tile redirect must remain https");
            resp.EnsureSuccessStatusCode();
            long? declared = resp.Content.Headers.ContentLength;
            if (declared.HasValue && (declared.Value < 8 || declared.Value > MaxCdnTileBytes))
                throw new InvalidDataException($"tile payload size out of range: {declared}");
            var output = new MemoryStream();
            var buffer = new byte[81920];
            using (Stream stream = await resp.Content.ReadAsStreamAsync().ConfigureAwait(false))
            using (var readCts = new System.Threading.CancellationTokenSource(BodyReadTimeout))
            {
                while (true)
                {
                    int n = await stream.ReadAsync(buffer, 0, buffer.Length, readCts.Token).ConfigureAwait(false);
                    if (n <= 0) break;
                    if (output.Length + n > MaxCdnTileBytes)
                        throw new InvalidDataException("tile payload exceeds size cap");
                    output.Write(buffer, 0, n);
                }
            }
            return output.ToArray();
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
                if (_missUntilTick.Count >= MissCachePruneThreshold)
                    PruneExpiredMissesLocked();
                _missUntilTick[key] = Environment.TickCount + MissCacheMs;
            }
        }

        /// <summary>Caller holds _lock. Drop deadlines already past (same wrap math as readers).</summary>
        void PruneExpiredMissesLocked()
        {
            int now = Environment.TickCount;
            List<long>? expired = null;
            foreach (var kv in _missUntilTick)
            {
                if (unchecked(now - kv.Value) >= 0)
                    (expired ??= new List<long>()).Add(kv.Key);
            }
            if (expired == null) return;
            foreach (long k in expired)
                _missUntilTick.Remove(k);
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
                    bytes = await FetchTileBytesAsync(url).ConfigureAwait(false);
                    if (bytes == null || bytes.Length < 8 || !RteTile.HasMagic(bytes))
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
                        $"CDN tile {tx},{tz} failed (failClosed={_cfg.FailClosedMissingTiles}): {ex.Message}");
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
            lock (_lock)
            {
                if (_foci.Count == 0)
                {
                    _hot.Clear();
                    return;
                }
                var centers = new List<(int tx, int tz)>(_foci.Count);
                foreach (var kv in _foci)
                    centers.Add((kv.Value.tx, kv.Value.tz));

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
