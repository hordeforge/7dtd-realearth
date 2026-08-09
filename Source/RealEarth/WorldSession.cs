using System;
using System.Collections;

namespace RealEarth
{
    /// <summary>
    /// Optional coordinate mapping on top of vanilla chunks.
    ///
    /// Vanilla already: chunk load/unload, shared world space, cross-chunk combat.
    /// RealEarth only: map engine (x,z) → absolute Earth for .rte sampling.
    ///
    /// LocalWindowSize + origin slide is a bound on engine coords if the world must
    /// grow past a fixed host size — NOT a separate multiplayer/chunk combat system.
    /// </summary>
    public sealed class WorldSession
    {
        readonly EarthCoords _coords;
        readonly RealEarthConfig _cfg;

        /// <summary>Earth-space block of local (0,0). Moves as the active window slides.</summary>
        public int OriginEarthX { get; private set; }
        public int OriginEarthZ { get; private set; }

        /// <summary>Last known absolute Earth position of the primary player.</summary>
        public int AbsoluteX { get; private set; }
        public int AbsoluteZ { get; private set; }

        public int LocalWindowSize => _cfg.LocalWindowSize;
        public string MapMode => _cfg.MapMode ?? "Streamed";
        public bool IsStreamed => !string.Equals(MapMode, "Baked", StringComparison.OrdinalIgnoreCase);
        public bool IsBaked => string.Equals(MapMode, "Baked", StringComparison.OrdinalIgnoreCase);

        /// <summary>Absolute Earth bounds currently covered by the host window [min, max).</summary>
        public void GetActiveWindowEarthBounds(out int minX, out int minZ, out int maxX, out int maxZ)
        {
            minX = OriginEarthX;
            minZ = OriginEarthZ;
            maxX = OriginEarthX + LocalWindowSize;
            maxZ = OriginEarthZ + LocalWindowSize;
        }

        public WorldSession(EarthCoords coords, RealEarthConfig cfg)
        {
            _coords = coords;
            _cfg = cfg;
            OriginEarthX = 0;
            OriginEarthZ = Math.Max(0, (_coords.WorldHeight - cfg.LocalWindowSize) / 2);
            AbsoluteX = OriginEarthX + cfg.LocalWindowSize / 2;
            AbsoluteZ = OriginEarthZ + cfg.LocalWindowSize / 2;
        }

        public void SetOrigin(int earthX, int earthZ)
        {
            if (_cfg.EnableLongitudeWrap)
                OriginEarthX = _coords.WrapX(earthX);
            else
                OriginEarthX = earthX;
            OriginEarthZ = _coords.ClampZ(earthZ);
        }

        /// <summary>
        /// Restore a saved snapshot exactly (origin + absolute). Does not recenter.
        /// </summary>
        public void RestoreSnapshot(int originEarthX, int originEarthZ, int absoluteX, int absoluteZ)
        {
            SetOrigin(originEarthX, originEarthZ);
            // Match LocalToEarth policy: wrap X only when longitude wrap enabled.
            if (_cfg.EnableLongitudeWrap)
                AbsoluteX = _coords.WrapX(absoluteX);
            else
                AbsoluteX = Math.Max(0, Math.Min(Math.Max(0, _coords.WorldWidth - 1), absoluteX));
            AbsoluteZ = _coords.ClampZ(absoluteZ);
            // Prefetch only (no sticky focusId=0); player tick registers real entity foci.
            ModApi.Streamer?.EnsureHotAround(
                AbsoluteX, AbsoluteZ,
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
            {
                AbsoluteX = earthX;
                AbsoluteZ = earthZ;
            }

            int half = LocalWindowSize / 2;
            int ox = earthX - half;
            int oz = earthZ - half;
            if (!_cfg.EnableLongitudeWrap)
                ox = Math.Max(0, Math.Min(Math.Max(0, _coords.WorldWidth - LocalWindowSize), ox));
            oz = Math.Max(0, Math.Min(Math.Max(0, _coords.WorldHeight - LocalWindowSize), oz));
            SetOrigin(ox, oz);
        }

        // Back-compat name
        public void CenterOnEarth(int earthX, int earthZ) => CenterWindowOnAbsolute(earthX, earthZ);

        public void LocalToEarth(int localX, int localZ, out int earthX, out int earthZ)
        {
            earthX = OriginEarthX + localX;
            earthZ = OriginEarthZ + localZ;
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
            if (_cfg.EnableLongitudeWrap || ShouldFoldHostIntoPack())
            {
                int dx = earthX - OriginEarthX;
                int w = Math.Max(1, _coords.WorldWidth);
                dx = ((dx % w) + w + w / 2) % w - w / 2;
                localX = dx;
            }
            else
            {
                localX = earthX - OriginEarthX;
            }
            if (ShouldFoldHostIntoPack() && !_cfg.EnableLongitudeWrap)
            {
                int dz = earthZ - OriginEarthZ;
                int h = Math.Max(1, _coords.WorldHeight);
                dz = ((dz % h) + h + h / 2) % h - h / 2;
                localZ = dz;
            }
            else
                localZ = earthZ - OriginEarthZ;
        }

        public void LonLatToLocal(double lon, double lat, out int localX, out int localZ)
        {
            LonLatToEarth(lon, lat, out int ex, out int ez);
            EarthToLocal(ex, ez, out localX, out localZ);
        }

        public void LocalToLonLat(int localX, int localZ, out double lon, out double lat)
        {
            LocalToEarth(localX, localZ, out int ex, out int ez);
            EarthToLonLat(ex, ez, out lon, out lat);
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
            {
                AbsoluteX = earthX;
                AbsoluteZ = earthZ;
            }

            // (2) Dynamic Earth tile load around this focus (union with other players)
            // Player path allows sync tile load so inject soon after has hot tiles.
            ModApi.Streamer?.UpdateFromAbsolute(earthX, earthZ, focusId, allowSyncLoad: true);

            // (3) Slide host window so absolute position stays centered
            if (!ShouldAllowOriginSlide())
                return false;

            // Refuse slide when land claims exist (builds would desync from absolute Earth).
            if (OriginSlideRemap.HasLandClaims())
            {
                if (SessionOriginPolicy.NeedsRecentering(localX, localZ, LocalWindowSize))
                    ModApi.Log(
                        "Origin slide refused: land claims present (SharedFixed / absolute builds).");
                return false;
            }

            // Recenter when player leaves the middle band of the host (P2 policy).
            if (SessionOriginPolicy.NeedsRecentering(localX, localZ, LocalWindowSize))
            {
                int oldOx = OriginEarthX;
                int oldOz = OriginEarthZ;
                CenterWindowOnAbsolute(earthX, earthZ, updateAbsolute: updateSessionAbsolute);
                originDeltaX = OriginEarthX - oldOx;
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

            return false;
        }

        /// <summary>
        /// Direct absolute update (server authority path). Always streams tiles;
        /// slides window when allowed.
        /// </summary>
        public bool TickAbsolute(int earthX, int earthZ, out int localX, out int localZ, int focusId = 0)
        {
            earthX = _coords.WrapX(earthX);
            earthZ = _coords.ClampZ(earthZ);
            AbsoluteX = earthX;
            AbsoluteZ = earthZ;
            ModApi.Streamer?.UpdateFromAbsolute(earthX, earthZ, focusId, allowSyncLoad: true);

            if (IsStreamed && ShouldAllowOriginSlide() && !OriginSlideRemap.HasLandClaims())
            {
                EarthToLocal(earthX, earthZ, out localX, out localZ);
                int margin = Math.Max(64, LocalWindowSize / 6);
                if (localX < margin || localX > LocalWindowSize - margin
                    || localZ < margin || localZ > LocalWindowSize - margin
                    || localX < 0 || localZ < 0
                    || localX >= LocalWindowSize || localZ >= LocalWindowSize)
                {
                    CenterWindowOnAbsolute(earthX, earthZ);
                    EarthToLocal(earthX, earthZ, out localX, out localZ);
                    return true;
                }
                return false;
            }

            EarthToLocal(earthX, earthZ, out localX, out localZ);
            return false;
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
        /// Public for HooksImpl dedicated absolute policy.
        /// </summary>
        public static int EstimatePlayerCount()
        {
            try
            {
                var gmType = Type.GetType("GameManager, Assembly-CSharp");
                var inst = gmType?.GetProperty("Instance")?.GetValue(null);
                var world = inst?.GetType().GetProperty("World")?.GetValue(inst);
                var players = world?.GetType().GetProperty("Players")?.GetValue(world);
                if (players == null) return -1;
                var countProp = players.GetType().GetProperty("Count");
                if (countProp != null)
                    return Convert.ToInt32(countProp.GetValue(players));
                if (players is ICollection col)
                    return col.Count;
                // list field on PlayerList-like types
                var listProp = players.GetType().GetProperty("list")
                    ?? players.GetType().GetProperty("List");
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
