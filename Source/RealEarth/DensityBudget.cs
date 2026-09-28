using System;

namespace RealEarth
{
    /// <summary>
    /// P6: density/sim budget caps so metro stamps do not melt the host.
    /// Pure clamps used by stamp planning, distance LODs, and sleeper weights.
    /// </summary>
    public static class DensityBudget
    {
        public const int DefaultMaxPrefabsPerChunk = 4;
        public const int DefaultMaxPrefabsPerKm2 = 80;

        /// <summary>Near band: full stamp + sleeper weight 1.0 (blocks).</summary>
        public const int NearBandMeters = 128;

        /// <summary>Mid band: stamp allowed, sleeper weight reduced (blocks).</summary>
        public const int MidBandMeters = 384;

        /// <summary>Far band: sleeper weight drops to 0 (blocks). No new POI places beyond this.</summary>
        public const int FarBandMeters = 768;

        public static int ClampPrefabsInChunk(int requested, int maxPerChunk = DefaultMaxPrefabsPerChunk)
        {
            if (requested < 0) return 0;
            int cap = Math.Max(0, maxPerChunk);
            return requested > cap ? cap : requested;
        }

        /// <summary>Same clamp as per-chunk; separate name keeps the budget unit in the signature.</summary>
        public static int ClampPrefabsInArea(int requested, int maxPerKm2 = DefaultMaxPrefabsPerKm2)
            => ClampPrefabsInChunk(requested, maxPerKm2);

        /// <summary>
        /// Distance from player to stamp site in blocks (XZ). Negative inputs clamp to 0.
        /// </summary>
        public static int DistanceBlocks(int playerX, int playerZ, int siteX, int siteZ)
        {
            long dx = (long)playerX - siteX;
            long dz = (long)playerZ - siteZ;
            double d = Math.Sqrt((double)(dx * dx + dz * dz));
            if (d < 0) return 0;
            if (d > int.MaxValue) return int.MaxValue;
            return (int)d;
        }

        /// <summary>
        /// True when a stamp at this distance is allowed. Stamps stay allowed
        /// through the far band; only sleeper weight drops there (see SleeperWeight).
        /// </summary>
        public static bool AllowStampAtDistance(int distanceBlocks)
        {
            if (distanceBlocks < 0) distanceBlocks = 0;
            return distanceBlocks <= FarBandMeters;
        }

        /// <summary>
        /// Sleeper / sim weight by distance band: near=1, mid=0.5, far=0 (drop).
        /// Used after place to decide whether to re-pin sleeper volumes.
        /// </summary>
        public static float SleeperWeight(int distanceBlocks)
        {
            if (distanceBlocks < 0) distanceBlocks = 0;
            if (distanceBlocks <= NearBandMeters) return 1f;
            if (distanceBlocks <= MidBandMeters) return 0.5f;
            return 0f;
        }
    }
}
