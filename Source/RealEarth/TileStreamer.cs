using System;
using System.Collections.Generic;
using System.Diagnostics;
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
    public sealed class TileStreamer : IDisposable
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
        /// <summary>Config-constant decision cached at construction; FoldPackZ runs
        /// on the per-block sample hot path and must not re-evaluate it each call.</summary>
        readonly bool _shouldFoldPack;

        /// <summary>
        /// Millisecond tick source with Environment.TickCount semantics (unchecked
        /// wrap-safe deltas). Injectable so every time-driven decision in the cache
        /// (miss negative-cache, stale-focus sweep, sync-load wait bounds) can be
        /// stepped by virtual time in a deterministic harness instead of wall clock.
        /// </summary>
        internal Func<int> TickNow { get; set; } = static () => Environment.TickCount;

        /// <summary>
        /// Backoff between in-flight claims in <see cref="WaitForHotOrClaim"/>. Paired
        /// with <see cref="TickNow"/>: both must be injectable, or a harness that
        /// freezes virtual time spins on real milliseconds and its wait never times out.
        /// </summary>
        internal static Action<int> SleepMs { get; set; } = static ms => System.Threading.Thread.Sleep(ms);

        /// <summary>
        /// Dispatch for the fire-and-forget async load. The default hands it to the
        /// thread pool, which makes the order in which tiles become hot a function of
        /// OS scheduling; a harness passes a dispatcher that runs the load inline so
        /// completion order is chosen, not raced for.
        /// </summary>
        internal static Action<Func<Task>> DispatchAsyncLoad { get; set; } = static body => _ = body();

        const int MissCacheMs = 10_000;
        /// <summary>Wait slice between in-flight claim retries (see SleepMs).</summary>
        const int ClaimRetrySliceMs = 5;
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
        /// Ceiling on async loads running at once. Each one holds an open HTTP
        /// response plus an 80 KB read buffer (CDN) or a thread-pool work item
        /// (disk), and the body deadline is 12 s, so a slow or hostile CDN lets
        /// the pending set grow with how fast the player covers new tiles: without
        /// a cap, one stalled origin slide becomes unbounded sockets and buffers.
        /// Over the cap a tile is left uncached and un-missed, so the next
        /// focus/sample pass re-requests it once a slot frees. The sync gen path
        /// takes no slot: it must complete or the chunk bakes ocean columns.
        /// </summary>
        internal const int MaxConcurrentAsyncLoads = 8;

        /// <summary>
        /// Keys currently holding one of the <see cref="MaxConcurrentAsyncLoads"/>
        /// slots. Tracked per key rather than as a bare counter so a load that
        /// loses its in-flight claim to a timed-out sync load still returns its
        /// own slot instead of leaking capacity. Caller holds _lock.
        /// </summary>
        readonly HashSet<long> _asyncLoadSlots = new HashSet<long>();

        /// <summary>
        /// Lines a failing tile load may print before the rest are counted instead
        /// (see LogBudget). One bad tile is re-queued every MissCacheMs per focus,
        /// so an unreadable tile root or a dead CDN would otherwise put one ERROR
        /// per tile per window into the server log and bury the real cause.
        /// </summary>
        internal const int LoadErrorLogSlots = 20;

        /// <summary>Shared by every load failure path; counted by `reinject` (suppressedErr).</summary>
        internal static readonly LogBudget LoadErrorBudget = new LogBudget(LoadErrorLogSlots);

        /// <summary>
        /// Log a tile load failure once per budget slot. Over-budget failures are
        /// counted, so `reinject` still shows the true rate behind a truncated log.
        /// </summary>
        static void LogLoadError(string msg)
        {
            if (LoadErrorBudget.Allow())
                ModApi.LogError(msg);
        }

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
            _shouldFoldPack = SessionOriginPolicy.ShouldFoldHostIntoPack(
                _cfg.SingleWorldSession, _cfg.HasRegionalBbox,
                _coords.WorldWidth, _coords.WorldHeight)
                && !_cfg.EnableLongitudeWrap;
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
            int now = TickNow();
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

            // HotRadiusTiles, not the raw field: a StreamRadiusTiles of 0 is a
            // legal config, and streaming only the single tile under the player
            // turns everything past the tile edge into fail-closed ocean.
            EnsureRadius(tx, tz, _cfg.HotRadiusTiles, allowSyncLoad);
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
        /// </summary>
        int FoldPackZ(int z)
            => SessionOriginPolicy.PackZ(z, _shouldFoldPack, longitudeWrap: false, coords: _coords);

        public void EnsureRadius(int centerTx, int centerTz, int radius)
            => EnsureRadius(centerTx, centerTz, radius, allowSyncLoad: false);

        public void EnsureRadius(int centerTx, int centerTz, int radius, bool allowSyncLoad)
        {
            // Hot path (per block sample / player tick): one lock pass filters already-hot
            // and miss-cached tiles; only genuine misses go through EnsureTile.
            List<long>? missing = null;
            int now = TickNow();
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
                int now = TickNow();
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
                    && unchecked(TickNow() - until) < 0)
                    return;
            }

            var path = TileFilePath(tx, tz);
            bool exists;
            try { exists = File.Exists(path); }
            catch (Exception ex)
            {
                // A throwing File.Exists means the tile root is unreadable (permissions,
                // unmounted volume): every tile would silently miss into ocean with zero
                // trace. Count + one budgeted line keeps the failure visible.
                TileLoadStats.AddExistsError();
                LogLoadError(
                    $"Tile root probe failed path={path}: {ex.GetType().Name}: {ex.Message}");
                exists = false;
            }

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
            int start = TickNow();
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
                if (unchecked(TickNow() - start) > maxWaitMs)
                {
                    // Timed out waiting; claim anyway so we can force a sync load after.
                    lock (_lock)
                    {
                        if (_hot.ContainsKey(key)) return false;
                        _loadInFlight.Add(key);
                        return true;
                    }
                }
                SleepMs(ClaimRetrySliceMs);
            }
        }

        void TryLoadCdnSync(int tx, int tz, string path, long key, string url)
        {
            if (!WaitForHotOrClaim(key, maxWaitMs: 12000))
                return;
            try
            {
                var sw = Stopwatch.StartNew();
                var bytes = FetchTileBytesAsync(url).ConfigureAwait(false).GetAwaiter().GetResult();
                if (bytes == null || bytes.Length < 8 || !RteTile.HasMagic(bytes))
                {
                    TileLoadStats.AddBadPayload();
                    TileLoadStats.AddCdnFail();
                    LogLoadError($"CDN sync tile {tx},{tz} url={url}: bad payload ({sw.ElapsedMilliseconds} ms)");
                    MarkMiss(key);
                    lock (_lock) { _loadInFlight.Remove(key); }
                    return;
                }
                var dir = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir))
                    Directory.CreateDirectory(dir);
                // Validate the full payload BEFORE durable publish: a body that passes
                // the magic check but fails decode must never reach the tile store,
                // where File.Exists would shadow the CDN on every later attempt and
                // pin this tile on fail-closed ocean until manual cleanup.
                var tile = RteTile.Decode(bytes);
                PublishTileBytes(path, bytes);
                lock (_lock)
                {
                    _hot[key] = tile;
                    _missUntilTick.Remove(key);
                    _loadInFlight.Remove(key);
                    TrimHotToCapLocked();
                }
                sw.Stop();
                TileLoadStats.AddCdnOk(sw.ElapsedMilliseconds);
            }
            catch (Exception ex)
            {
                TileLoadStats.AddCdnFail();
                LogLoadError($"CDN sync tile {tx},{tz} url={url}: {ex.GetType().Name}: {ex.Message}");
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
                // Backpressure: leave the tile uncached and un-missed so a later
                // pass retries it. Caching a miss here would pin the tile on
                // fail-closed ocean for MissCacheMs because no load ever ran.
                if (_asyncLoadSlots.Count >= MaxConcurrentAsyncLoads) return;
                start = _loadInFlight.Add(key);
                if (start) _asyncLoadSlots.Add(key);
            }
            if (!start) return;
            try
            {
                DispatchAsyncLoad(() => LoadTileFireAndForget(tx, tz, path, key, fromCdn));
            }
            catch (Exception ex)
            {
                // A dispatcher that throws synchronously (shut-down thread pool, a
                // harness that rejects the work) never reaches the load's finally,
                // and the claim would pin this tile for the whole server uptime.
                bool released;
                lock (_lock)
                {
                    released = _asyncLoadSlots.Remove(key);
                    _loadInFlight.Remove(key);
                }
                if (released)
                    LogLoadError($"Tile load dispatch failed for {tx},{tz}: {ex.GetType().Name}: {ex.Message}");
            }
        }

        void TryLoadLocalSync(int tx, int tz, string path, long key)
        {
            try
            {
                var sw = Stopwatch.StartNew();
                var tile = RteTile.Load(path);
                lock (_lock)
                {
                    _hot[key] = tile;
                    _missUntilTick.Remove(key);
                    _loadInFlight.Remove(key);
                    TrimHotToCapLocked();
                }
                sw.Stop();
                TileLoadStats.AddDiskOk(sw.ElapsedMilliseconds);
            }
            catch (Exception ex)
            {
                TileLoadStats.AddDiskFail();
                LogLoadError($"Load tile {tx},{tz} path={path}: {ex.GetType().Name}: {ex.Message}");
                MarkMiss(key);
                lock (_lock) { _loadInFlight.Remove(key); }
            }
        }

        void MarkMiss(long key)
        {
            lock (_lock)
            {
                if (_missUntilTick.Count >= MissCachePruneThreshold)
                {
                    PruneExpiredMissesLocked();
                    // A storm can exceed the threshold with nothing expired yet (more
                    // distinct failing tiles inside one MissCacheMs window than the
                    // bound); drop entries until the map is back under the bound. Which
                    // entries go is unspecified (Dictionary order); every value is a miss
                    // deadline, so any is equally droppable.
                    while (_missUntilTick.Count >= MissCachePruneThreshold)
                    {
                        long head = 0;
                        foreach (var kv in _missUntilTick) { head = kv.Key; break; }
                        _missUntilTick.Remove(head);
                    }
                }
                _missUntilTick[key] = TickNow() + MissCacheMs;
            }
        }

        /// <summary>Caller holds _lock. Drop deadlines already past (same wrap math as readers).</summary>
        void PruneExpiredMissesLocked()
        {
            int now = TickNow();
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
            // url is resolved inside the try: the finally below owns the in-flight
            // claim and the concurrency slot, so nothing this method evaluates may
            // run before it.
            string? url = null;
            var sw = Stopwatch.StartNew();
            try
            {
                url = fromCdn ? CdnTilePolicy.TileUrl(_cfg.TileCdnBaseUrl, tx, tz) : null;
                byte[] bytes;
                RteTile tile;
                if (fromCdn)
                {
                    if (url == null)
                    {
                        MarkMiss(key);
                        return;
                    }
                    bytes = await FetchTileBytesAsync(url).ConfigureAwait(false);
                    if (bytes == null || bytes.Length < 8 || !RteTile.HasMagic(bytes))
                    {
                        TileLoadStats.AddBadPayload();
                        TileLoadStats.AddCdnFail();
                        LogLoadError(
                            $"CDN tile {tx},{tz} url={url}: bad payload (not RTE1) after {sw.ElapsedMilliseconds} ms");
                        MarkMiss(key);
                        return;
                    }
                    // Decode before publish (same rationale as the sync CDN path):
                    // only fully validated payloads may enter the durable tile store.
                    tile = RteTile.Decode(bytes);
                    PublishTileBytes(path, bytes);
                }
                else
                {
                    // Disk decode off inject thread.
                    bytes = await Task.Run(() => File.ReadAllBytes(path)).ConfigureAwait(false);
                    tile = RteTile.Decode(bytes);
                }

                lock (_lock)
                {
                    _hot[key] = tile;
                    _missUntilTick.Remove(key);
                    TrimHotToCapLocked();
                }
                sw.Stop();
                if (fromCdn)
                    TileLoadStats.AddCdnOk(sw.ElapsedMilliseconds);
                else
                    TileLoadStats.AddDiskOk(sw.ElapsedMilliseconds);
            }
            catch (Exception ex)
            {
                if (fromCdn)
                {
                    TileLoadStats.AddCdnFail();
                    LogLoadError(
                        $"CDN tile {tx},{tz} url={url} failed after {sw.ElapsedMilliseconds} ms " +
                        $"(failClosed={_cfg.FailClosedMissingTiles}): {ex.GetType().Name}: {ex.Message}");
                }
                else
                {
                    TileLoadStats.AddDiskFail();
                    LogLoadError(
                        $"Async load tile {tx},{tz} path={path} failed after {sw.ElapsedMilliseconds} ms: " +
                        $"{ex.GetType().Name}: {ex.Message}");
                }
                MarkMiss(key);
            }
            finally
            {
                lock (_lock)
                {
                    // Paired with the claim QueueLoad took. The slot is what bounds
                    // concurrent loads, so it must return on every exit path.
                    _asyncLoadSlots.Remove(key);
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

                TrimHotToCapLocked(centers);
            }
        }

        /// <summary>
        /// Cap check for load-completion paths (disk, CDN, prefetch), which add tiles
        /// without running focus eviction.
        /// </summary>
        void TrimHotToCapLocked()
        {
            if (_cfg.MaxHotTiles <= 0 || _hot.Count <= _cfg.MaxHotTiles)
                return;
            var centers = new List<(int tx, int tz)>(_foci.Count);
            foreach (var kv in _foci)
                centers.Add((kv.Value.tx, kv.Value.tz));
            TrimHotToCapLocked(centers);
        }

        /// <summary>
        /// Drop the tiles farthest from their nearest focus once the hot set passes
        /// <see cref="RealEarthConfig.MaxHotTiles"/>. Focus-radius eviction alone grows
        /// with player count (a decoded tile is ~1.5 MB), so the cap is what bounds
        /// resident memory; the dropped tiles reload on demand.
        /// </summary>
        void TrimHotToCapLocked(List<(int tx, int tz)> centers)
        {
            int cap = _cfg.MaxHotTiles;
            if (cap <= 0 || _hot.Count <= cap)
                return;
            if (centers.Count == 0)
            {
                _hot.Clear();
                return;
            }

            var ranked = new List<(long distSq, long key)>(_hot.Count);
            foreach (var kv in _hot)
            {
                int tx = (int)(kv.Key >> 32);
                int tz = (int)(kv.Key & 0xffffffff);
                long best = long.MaxValue;
                foreach (var c in centers)
                {
                    long dx = Math.Abs((long)tx - c.tx);
                    long dz = Math.Abs((long)tz - c.tz);
                    if (_cfg.EnableLongitudeWrap)
                    {
                        int ntx = _coords.TilesX;
                        if (ntx > 0)
                        {
                            // Fold into [0, ntx) first: a focus outside the grid
                            // makes the raw delta exceed the circumference, and
                            // ntx - dx would then go negative, so squaring it
                            // ranked the farthest tile as nearest.
                            dx %= ntx;
                            dx = Math.Min(dx, ntx - dx);
                        }
                    }
                    long d = dx * dx + dz * dz;
                    if (d < best)
                        best = d;
                }
                ranked.Add((best, kv.Key));
            }
            // Nearest first: the tail past the cap is what leaves the cache.
            ranked.Sort();
            for (int i = cap; i < ranked.Count; i++)
                _hot.Remove(ranked[i].key);
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
                    {
                        // Fold first: an out-of-grid focus makes the raw delta
                        // exceed the circumference, and the unguarded form below
                        // went negative, so the radius test admitted every far tile.
                        dx %= ntx;
                        dx = Math.Min(dx, ntx - dx);
                    }
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

        /// <summary>
        /// Release the CDN client and the decoded tile cache. The streamer's
        /// lifetime is the process, so this runs when ModApi replaces the
        /// instance (a re-init after a game update reload, a dedicated world
        /// switch under a host that re-runs IModApi.InitMod): without it every
        /// replacement strands the previous HttpClient's connection pool and
        /// its ~1.5 MB-per-tile hot set. In-flight loads fail against the
        /// disposed client and land in the normal miss path.
        /// </summary>
        public void Dispose()
        {
            lock (_lock)
            {
                _hot.Clear();
                _missUntilTick.Clear();
                _foci.Clear();
                _asyncLoadSlots.Clear();
            }
            _http.Dispose();
            GC.SuppressFinalize(this);
        }
    }
}
