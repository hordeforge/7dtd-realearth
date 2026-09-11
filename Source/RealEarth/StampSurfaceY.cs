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
        /// Sleeper volume root Y on the same surface as the prefab stamp.
        /// Same math as PrefabRootY; separate name keeps the call site explicit.
        /// </summary>
        public static int SleeperRootY(int surfaceGameY, int foundationOffsetBlocks = 0)
            => PrefabRootY(surfaceGameY, foundationOffsetBlocks);
    }
}
