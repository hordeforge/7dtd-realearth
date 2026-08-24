using System;

namespace RealEarth
{
    /// <summary>
    /// P6: density/sim budget caps so metro stamps do not melt the host.
    /// Pure clamps used by stamp planning and (later) spawner weights.
    /// </summary>
    public static class DensityBudget
    {
        public const int DefaultMaxPrefabsPerChunk = 4;
        public const int DefaultMaxPrefabsPerKm2 = 80;

        public static int ClampPrefabsInChunk(int requested, int maxPerChunk = DefaultMaxPrefabsPerChunk)
        {
            if (requested < 0) return 0;
            int cap = Math.Max(0, maxPerChunk);
            return requested > cap ? cap : requested;
        }

        /// <summary>Same clamp as per-chunk; separate name keeps the budget unit in the signature.</summary>
        public static int ClampPrefabsInArea(int requested, int maxPerKm2 = DefaultMaxPrefabsPerKm2)
            => ClampPrefabsInChunk(requested, maxPerKm2);
    }
}
