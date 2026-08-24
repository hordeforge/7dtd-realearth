using System;

namespace RealEarth
{
    /// <summary>
    /// P2/P5: pure origin-slide and host-fold policy (mirrors WorldSession).
    /// Offline-testable without Unity.
    /// </summary>
    public static class SessionOriginPolicy
    {
        public static bool ShouldFoldHostIntoPack(
            bool singleWorldSession,
            bool hasRegionalBbox,
            int worldWidth,
            int worldHeight)
        {
            if (singleWorldSession) return true;
            if (hasRegionalBbox) return true;
            return worldWidth <= 65536 && worldHeight <= 65536;
        }

        public static int FoldCoord(int v, int extent)
        {
            int e = Math.Max(1, extent);
            int r = v % e;
            return r < 0 ? r + e : r;
        }

        /// <summary>
        /// Shortest signed origin delta on a wrapping axis, using the exact fold
        /// from WorldSession.EarthToLocal. A slide across the antimeridian is a few
        /// hundred blocks forward, never minus-planet-width; OriginSlideRemap entity
        /// shifts and the PlayerTickPostfix rollback consume this delta raw.
        /// Non-wrapping callers keep plain subtraction (fold mode origins are clamped).
        /// </summary>
        public static int WrappedDelta(int delta, int extent)
        {
            int e = Math.Max(1, extent);
            return ((delta % e) + e + e / 2) % e - e / 2;
        }

        /// <summary>
        /// SharedFixed never slides.
        /// SoloSlide / SharedSlide only when player count is known and ≤ 1.
        /// Unknown count (&lt; 0) fails closed (no slide) so MP cannot desync on bad reflection.
        /// </summary>
        public static bool AllowOriginSlide(
            string? multiplayerOriginMode,
            int localWindowSize,
            int worldWidth,
            int worldHeight,
            int estimatedPlayerCount)
        {
            if (localWindowSize >= worldWidth && localWindowSize >= worldHeight)
                return false;
            var mode = (multiplayerOriginMode ?? "SoloSlide").Trim();
            if (mode.Equals("SharedFixed", StringComparison.OrdinalIgnoreCase))
                return false;
            // Fail closed when player count is unknown (reflection miss).
            if (estimatedPlayerCount < 0)
                return false;
            if (mode.Equals("SoloSlide", StringComparison.OrdinalIgnoreCase))
                return estimatedPlayerCount <= 1;
            if (mode.Equals("SharedSlide", StringComparison.OrdinalIgnoreCase))
                return estimatedPlayerCount <= 1;
            // Unknown mode: only slide when clearly solo.
            return estimatedPlayerCount <= 1;
        }

        /// <summary>Whether local position is outside the center band (needs recenter).</summary>
        public static bool NeedsRecentering(int localX, int localZ, int localWindowSize)
        {
            int half = localWindowSize / 2;
            int margin = Math.Max(64, localWindowSize / 6);
            // Degenerate tiny window: the band covers the whole host, so every
            // position reads as "outside" and the origin would slide on every
            // tick (entity remap + hot-cache invalidate + chunk reinject churn).
            // No meaningful center band exists → never demand a slide.
            if (margin >= half)
                return false;
            int maxDrift = half - margin;
            int driftX = Math.Abs(localX - half);
            int driftZ = Math.Abs(localZ - half);
            if (driftX > maxDrift || driftZ > maxDrift) return true;
            if (localX < margin || localX > localWindowSize - margin) return true;
            if (localZ < margin || localZ > localWindowSize - margin) return true;
            return false;
        }

        /// <summary>
        /// After origin moves by (dOx, dOz) in Earth space, local entity coords shift by -delta
        /// so absolute Earth positions stay fixed.
        /// </summary>
        public static void RemapLocalAfterOriginDelta(
            int localX, int localZ, int originDeltaX, int originDeltaZ,
            out int newLocalX, out int newLocalZ)
        {
            newLocalX = localX - originDeltaX;
            newLocalZ = localZ - originDeltaZ;
        }
    }
}
