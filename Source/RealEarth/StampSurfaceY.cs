using System;

namespace RealEarth
{
    /// <summary>
    /// P3: place prefab/POI Y on real terrain surface (not floating stock Y).
    /// Pure math used by density stamp planning and inject-side placement.
    /// </summary>
    public static class StampSurfaceY
    {
        /// <summary>
        /// Prefab root Y = surface game Y + foundation offset (blocks into ground negative, or pad positive).
        /// </summary>
        public static int PrefabRootY(int surfaceGameY, int foundationOffsetBlocks = 0)
        {
            int y = surfaceGameY + foundationOffsetBlocks;
            return y < 1 ? 1 : y;
        }

        /// <summary>
        /// Sleeper volume floor sits on surface (or slightly above pad).
        /// </summary>
        public static int SleeperFloorY(int surfaceGameY, int padBlocks = 0)
        {
            return PrefabRootY(surfaceGameY, Math.Max(0, padBlocks));
        }

        /// <summary>
        /// True if stamp Y is consistent with a known surface sample (within tolerance).
        /// </summary>
        public static bool IsSurfaceRelative(int stampY, int surfaceGameY, int tolerance = 2)
        {
            return Math.Abs(stampY - surfaceGameY) <= Math.Max(0, tolerance);
        }
    }
}
