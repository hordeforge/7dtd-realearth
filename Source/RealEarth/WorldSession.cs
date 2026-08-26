using System;
using System.Collections;
using System.Threading;

namespace RealEarth
{
    /// <summary>
    /// Optional coordinate mapping on top of vanilla chunks.
    ///
    /// Vanilla already: chunk load/unload, shared world space, cross-chunk combat.
    /// RealEarth only: map engine (x,z) → absolute Earth for .rte sampling.
    ///
    /// LocalWindowSize + origin slide is a bound on engine coords if the world must
    /// grow past a fixed host size, NOT a separate multiplayer/chunk combat system.
    /// </summary>
    public sealed class WorldSession
    {
        readonly EarthCoords _coords;
        readonly RealEarthConfig _cfg;

        // Origin/absolute pairs are written by the player/sim thread (origin slide,
        // tick updates) and read by the chunk-generation thread plus height-query
        // hooks. Each XZ pair lives in one packed long published via Volatile.Read/
        // Write so readers never observe a half-applied slide (new X with old Z
        // would inject wrong-Earth columns).
        long _originPacked;
        long _absolutePacked;

        static long PackXZ(int x, int z) => ((long)x << 32) | (uint)z;
        static int UnpackX(long p) => (int)(p >> 32);
        static int UnpackZ(long p) => unchecked((int)(p & 0xffffffffL));

        void WriteOriginLocked(int earthX, int earthZ)
            => Volatile.Write(ref _originPacked, PackXZ(earthX, earthZ));

        /// <summary>Read origin as one consistent XZ pair (never torn across a slide).</summary>
        public void ReadOrigin(out int originX, out int originZ)
        {
            long p = Volatile.Read(ref _originPacked);
            originX = UnpackX(p);
            originZ = UnpackZ(p);
        }

        void WriteAbsolute(int x, int z)
            => Volatile.Write(ref _absolutePacked, PackXZ(x, z));

        /// <summary>Read absolute position as one consistent XZ pair.</summary>
        public void ReadAbsolute(out int ax, out int az)
        {
            long p = Volatile.Read(ref _absolutePacked);
            ax = UnpackX(p);
            az = UnpackZ(p);
        }

        /// <summary>Earth-space block of local (0,0). Moves as the active window slides.</summary>
        public int OriginEarthX { get { ReadOrigin(out int ox, out _); return ox; } }
        public int OriginEarthZ { get { ReadOrigin(out _, out int oz); return oz; } }

        /// <summary>Last known absolute Earth position of the primary player.</summary>
        public int AbsoluteX { get { ReadAbsolute(out int ax, out _); return ax; } }
        public int AbsoluteZ { get { ReadAbsolute(out _, out int az); return az; } }

        public int LocalWindowSize => _cfg.LocalWindowSize;
        public string MapMode => _cfg.MapMode ?? "Streamed";
        public bool IsStreamed => !string.Equals(MapMode, "Baked", StringComparison.OrdinalIgnoreCase);
        public bool IsBaked => string.Equals(MapMode, "Baked", StringComparison.OrdinalIgnoreCase);

        /// <summary>Absolute Earth bounds currently covered by the host window [min, max).</summary>
        public void GetActiveWindowEarthBounds(out int minX, out int minZ, out int maxX, out int maxZ)
        {
            ReadOrigin(out int ox, out int oz);
            minX = ox;
            minZ = oz;
            maxX = ox + LocalWindowSize;
            maxZ = oz + LocalWindowSize;
        }

        public WorldSession(EarthCoords coords, RealEarthConfig cfg)
        {
            _coords = coords;
            _cfg = cfg;
            int ox = 0;
            int oz = Math.Max(0, (_coords.WorldHeight - cfg.LocalWindowSize) / 2);
            WriteOriginLocked(ox, oz);
            WriteAbsolute(ox + cfg.LocalWindowSize / 2, oz + cfg.LocalWindowSize / 2);
        }

        public void SetOrigin(int earthX, int earthZ)
        {
            int ox = _cfg.EnableLongitudeWrap ? _coords.WrapX(earthX) : earthX;
            int oz = _coords.ClampZ(earthZ);
            WriteOriginLocked(ox, oz);
        }

        /// <summary>
        /// Restore a saved snapshot exactly (origin + absolute). Does not recenter.
        /// </summary>
        public void RestoreSnapshot(int originEarthX, int originEarthZ, int absoluteX, int absoluteZ)
        {
            SetOrigin(originEarthX, originEarthZ);
            // Match LocalToEarth policy: wrap X only when longitude wrap enabled.
            if (_cfg.EnableLongitudeWrap)
                absoluteX = _coords.WrapX(absoluteX);
            else
                absoluteX = Math.Max(0, Math.Min(Math.Max(0, _coords.WorldWidth - 1), absoluteX));
            absoluteZ = _coords.ClampZ(absoluteZ);
            WriteAbsolute(absoluteX, absoluteZ);
            // Prefetch only (no sticky focusId=0); player tick registers real entity foci.
            ModApi.Streamer?.EnsureHotAround(
                absoluteX, absoluteZ,
                radius: Math.Max(1, _cfg.StreamRadiusTiles),
                allowSyncLoad: true);
        }

        /// <summary>
        /// Place host window so absolute (earthX, earthZ) is at the center.
        /// This is the core of dynamic loading: active window follows absolute position.
        /// </summary>
        public void CenterWindowOnAbsolute(int earthX, int earthZ)
            => CenterWindowOnAbsolute(earthX, earthZ, updateAbsolute: true);

        /// <param name="updateAbsolute">When false, only origin slides; durable AbsoluteX/Z stay put (MP non-primary).</param>
        public void CenterWindowOnAbsolute(int earthX, int earthZ, bool updateAbsolute)
        {
            earthX = _coords.WrapX(earthX);
            earthZ = _coords.ClampZ(earthZ);
            if (updateAbsolute)
                WriteAbsolute(earthX, earthZ);

            int half = LocalWindowSize / 2;
            int ox = earthX - half;
            int oz = earthZ - half;
            if (!_cfg.EnableLongitudeWrap)
                ox = Math.Max(0, Math.Min(Math.Max(0, _coords.WorldWidth - LocalWindowSize), ox));
            oz = Math.Max(0, Math.Min(Math.Max(0, _coords.WorldHeight - LocalWindowSize), oz));
            SetOrigin(ox, oz);
        }

        public void LocalToEarth(int localX, int localZ, out int earthX, out int earthZ)
        {
            ReadOrigin(out int ox, out int oz);
            earthX = ox + localX;
            earthZ = oz + localZ;
            // Always fold into pack grid. Host worlds (RWG / large baked) generate chunks
            // far outside 0..packSize; without this, inject sampled earthX=32768 and
            // only ClampZ to the pack edge (plains forever).
            if (_cfg.EnableLongitudeWrap || ShouldFoldHostIntoPack())
                earthX = _coords.WrapX(earthX);
            else
                earthX = Math.Max(0, Math.Min(Math.Max(0, _coords.WorldWidth - 1), earthX));
            earthZ = FoldZ(earthZ);
        }

        /// <summary>
        /// Regional single-map packs tile across any host size so every host chunk
        /// maps into the .rte grid (512×512 H500/Everest test, etc.).
        /// </summary>
        bool ShouldFoldHostIntoPack() =>
            SessionOriginPolicy.ShouldFoldHostIntoPack(
                _cfg.SingleWorldSession,
                _cfg.HasRegionalBbox,
                _coords.WorldWidth,
                _coords.WorldHeight);

        int FoldZ(int z)
        {
            if (ShouldFoldHostIntoPack() && !_cfg.EnableLongitudeWrap)
                return SessionOriginPolicy.FoldCoord(z, _coords.WorldHeight);
            return _coords.ClampZ(z);
        }

        public void EarthToLocal(int earthX, int earthZ, out int localX, out int localZ)
        {
            ReadOrigin(out int ox, out int oz);
            if (_cfg.EnableLongitudeWrap || ShouldFoldHostIntoPack())
            {
                // Same shortest-delta fold as seam-crossing slides; one copy of the formula.
                localX = SessionOriginPolicy.WrappedDelta(earthX - ox, _coords.WorldWidth);
            }
            else
            {
                localX = earthX - ox;
            }
            if (ShouldFoldHostIntoPack() && !_cfg.EnableLongitudeWrap)
                localZ = SessionOriginPolicy.WrappedDelta(earthZ - oz, _coords.WorldHeight);
            else
                localZ = earthZ - oz;
        }

        public void LonLatToLocal(double lon, double lat, out int localX, out int localZ)
        {
            LonLatToEarth(lon, lat, out int ex, out int ez);
            EarthToLocal(ex, ez, out localX, out localZ);
        }

        /// <summary>
        /// Lon/lat → pack/Earth block. Regional packs with bbox map linearly into the pack grid.
        /// </summary>
        public void LonLatToEarth(double lon, double lat, out int earthX, out int earthZ)
        {
            if (_cfg.HasRegionalBbox)
            {
                double west = _cfg.BboxWest;
                double south = _cfg.BboxSouth;
                double east = _cfg.BboxEast;
                double north = _cfg.BboxNorth;
                if (lon < west) lon = west;
                if (lon > east) lon = east;
                if (lat < south) lat = south;
                if (lat > north) lat = north;
                double fx = (lon - west) / (east - west);
                double fz = (north - lat) / (north - south);
                earthX = (int)(fx * Math.Max(1, _coords.WorldWidth - 1));
                earthZ = (int)(fz * Math.Max(1, _coords.WorldHeight - 1));
                if (_cfg.EnableLongitudeWrap)
                    earthX = _coords.WrapX(earthX);
                else
                    earthX = Math.Max(0, Math.Min(_coords.WorldWidth - 1, earthX));
                earthZ = _coords.ClampZ(earthZ);
                return;
            }
            _coords.LonLatToBlock(lon, lat, out earthX, out earthZ);
        }

        public void EarthToLonLat(int earthX, int earthZ, out double lon, out double lat)
        {
            if (_cfg.HasRegionalBbox)
            {
                double west = _cfg.BboxWest;
                double south = _cfg.BboxSouth;
                double east = _cfg.BboxEast;
                double north = _cfg.BboxNorth;
                double fx = earthX / (double)Math.Max(1, _coords.WorldWidth - 1);
                double fz = earthZ / (double)Math.Max(1, _coords.WorldHeight - 1);
                lon = west + fx * (east - west);
                lat = north - fz * (north - south);
                return;
            }
            _coords.BlockToLonLat(earthX, earthZ, out lon, out lat);
        }

        /// <summary>
        /// Drive dynamic loading from engine-local player position each tick:
        /// 1) Resolve absolute Earth position
        /// 2) Stream .rte tiles around this player's absolute pos (MP: per-focus bubble)
        /// 3) If near host edge and slide allowed, recenter host window on absolute pos
        ///    and return remapped local coords (player stays in middle of active window)
        /// </summary>
        /// <param name="focusId">Stable player/entity id for multi-player tile bubbles (0 = primary).</param>
        /// <param name="originDeltaX">Earth origin delta X when slide occurred (0 if no slide).</param>
        /// <param name="originDeltaZ">Earth origin delta Z when slide occurred (0 if no slide).</param>
        public bool TickPlayerLocal(
            int localX, int localZ,
            out int newLocalX, out int newLocalZ,
            int focusId = 0)
        {
            return TickPlayerLocal(
                localX, localZ, out newLocalX, out newLocalZ, out _, out _, focusId,
                updateSessionAbsolute: true);
        }

        public bool TickPlayerLocal(
            int localX, int localZ,
            out int newLocalX, out int newLocalZ,
            out int originDeltaX, out int originDeltaZ,
            int focusId = 0,
            bool updateSessionAbsolute = true)
        {
            newLocalX = localX;
            newLocalZ = localZ;
            originDeltaX = 0;
            originDeltaZ = 0;
            if (!IsStreamed)
                return false;

            LocalToEarth(localX, localZ, out int earthX, out int earthZ);
            // MP: only primary/local player updates durable session absolute (avoid last-tick stomp).
            if (updateSessionAbsolute)
                WriteAbsolute(earthX, earthZ);

            // (2) Dynamic Earth tile load around this focus (union with other players)
            // Player path allows sync tile load so inject soon after has hot tiles.
            ModApi.Streamer?.UpdateFromAbsolute(earthX, earthZ, focusId, allowSyncLoad: true);

            // (3) Slide host window so absolute position stays centered
            if (!ShouldAllowOriginSlide())
                return false;

            // Recenter when player leaves the middle band of the host (P2 policy).
            // NeedsRecentering runs first: HasLandClaims reflects over every player's
            // claim collections, and the old order ran that scan on every streamed tick
            // even while the player sat mid-window.
            if (!SessionOriginPolicy.NeedsRecentering(localX, localZ, LocalWindowSize))
                return false;

            // Refuse slide when land claims exist (builds would desync from absolute Earth).
            if (OriginSlideRemap.HasLandClaims())
            {
                ModApi.Log(
                    "Origin slide refused: land claims present (SharedFixed / absolute builds).");
                return false;
            }

            ReadOrigin(out int oldOx, out int oldOz);
            CenterWindowOnAbsolute(earthX, earthZ, updateAbsolute: updateSessionAbsolute);
            // Wrap mode: SetOrigin folds the origin into [0,W), so a seam-crossing
            // slide needs the shortest wrapped delta (raw subtraction would report
            // ~-40M and teleport every remapped entity across the planet).
            originDeltaX = _cfg.EnableLongitudeWrap
                ? SessionOriginPolicy.WrappedDelta(OriginEarthX - oldOx, _coords.WorldWidth)
                : OriginEarthX - oldOx;
            // Z clamps, never wraps: raw delta is always the true shift.
            originDeltaZ = OriginEarthZ - oldOz;
            // After recenter, absolute stays put when updateSessionAbsolute; local becomes center-ish
            EarthToLocal(earthX, earthZ, out newLocalX, out newLocalZ);
            newLocalX = Math.Max(1, Math.Min(LocalWindowSize - 2, newLocalX));
            newLocalZ = Math.Max(1, Math.Min(LocalWindowSize - 2, newLocalZ));
            ModApi.Log(
                $"Active window slid to absolute=({earthX},{earthZ}) " +
                $"origin=({OriginEarthX},{OriginEarthZ}) local→({newLocalX},{newLocalZ}) " +
                $"dOrigin=({originDeltaX},{originDeltaZ}) updateAbs={updateSessionAbsolute}");
            return true;
        }

        public bool ShouldAllowOriginSlide()
        {
            // SharedFixed / SoloSlide / host-covers-pack via pure SessionOriginPolicy (P2/P5).
            return SessionOriginPolicy.AllowOriginSlide(
                _cfg.MultiplayerOriginMode,
                LocalWindowSize,
                _coords.WorldWidth,
                _coords.WorldHeight,
                EstimatePlayerCount());
        }

        /// <summary>
        /// Known player count, or -1 when unknown (reflection miss). Unknown fails closed for slides.
        /// Public for HooksImpl dedicated absolute policy. Per-frame path: the result is
        /// TTL-cached because every player tick resolves it via a four-deep reflection
        /// chain (GameManager.Instance → World → Players → Count) twice for non-primary
        /// entities; player count only changes at human timescales (join/disconnect).
        /// </summary>
        public const int PlayerCountCacheMs = 500;
        static readonly object _playerCountGate = new object();
        static bool _playerCountCacheValid;
        static int _playerCountCached;
        static int _playerCountCacheExpiry;

        public static int EstimatePlayerCount()
        {
            int now = Environment.TickCount;
            lock (_playerCountGate)
            {
                if (_playerCountCacheValid && unchecked(now - _playerCountCacheExpiry) < 0)
                    return _playerCountCached;
            }

            int n = EstimatePlayerCountUncached();
            lock (_playerCountGate)
            {
                _playerCountCached = n;
                _playerCountCacheExpiry = Environment.TickCount + PlayerCountCacheMs;
                _playerCountCacheValid = true;
            }
            return n;
        }

        static int EstimatePlayerCountUncached()
        {
            try
            {
                var gmType = Type.GetType("GameManager, Assembly-CSharp");
                var inst = gmType != null
                    ? ReflectCache.PropPub(gmType, "Instance")?.GetValue(null)
                    : null;
                var world = inst != null
                    ? ReflectCache.PropPub(inst.GetType(), "World")?.GetValue(inst)
                    : null;
                if (world == null) return -1;
                var players = ReflectCache.PropPub(world.GetType(), "Players")?.GetValue(world);
                if (players == null) return -1;
                var pt = players.GetType();
                var countProp = ReflectCache.PropPub(pt, "Count");
                if (countProp != null)
                    return Convert.ToInt32(countProp.GetValue(players));
                if (players is ICollection col)
                    return col.Count;
                // list field on PlayerList-like types
                var listProp = ReflectCache.PropPub(pt, "list")
                    ?? ReflectCache.PropPub(pt, "List");
                if (listProp?.GetValue(players) is ICollection listCol)
                    return listCol.Count;
            }
            catch
            {
                // ignore
            }
            return -1;
        }

        /// <summary>
        /// Whether this tick should write durable AbsoluteX/Z.
        /// Local/primary always; also when player count is known and ≤1 (dedicated solo has no EntityPlayerLocal).
        /// </summary>
        public static bool ShouldUpdateSessionAbsolute(bool isLocalOrPrimaryPlayer)
        {
            if (isLocalOrPrimaryPlayer) return true;
            int n = EstimatePlayerCount();
            return n >= 0 && n <= 1;
        }

        public void SpawnAtLonLat(double lon, double lat)
        {
            LonLatToEarth(lon, lat, out int ex, out int ez);
            CenterWindowOnAbsolute(ex, ez);
            // Prefetch only (no sticky focusId=0); player tick registers real entity foci.
            ModApi.Streamer?.EnsureHotAround(ex, ez, radius: Math.Max(1, ModApi.Config?.StreamRadiusTiles ?? 2), allowSyncLoad: true);
            GetActiveWindowEarthBounds(out int minX, out int minZ, out int maxX, out int maxZ);
            ModApi.Log(
                $"Spawn absolute lon={lon:0.####} lat={lat:0.####} earth=({ex},{ez}); " +
                $"active window earth X[{minX},{maxX}) Z[{minZ},{maxZ}) size={LocalWindowSize}");
        }
    }
}
