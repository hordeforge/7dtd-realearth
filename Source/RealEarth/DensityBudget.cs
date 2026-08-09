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
        public const float DefaultMaxSleeperWeight = 1.0f;

        public static int ClampPrefabsInChunk(int requested, int maxPerChunk = DefaultMaxPrefabsPerChunk)
        {
            if (requested < 0) return 0;
            int cap = Math.Max(0, maxPerChunk);
            return requested > cap ? cap : requested;
        }

        public static int ClampPrefabsInArea(int requested, int maxPerKm2 = DefaultMaxPrefabsPerKm2)
        {
            if (requested < 0) return 0;
            int cap = Math.Max(0, maxPerKm2);
            return requested > cap ? cap : requested;
        }

        /// <summary>Metro band weight scaled then capped (0..maxWeight).</summary>
        public static float ClampSleeperWeight(float raw, float maxWeight = DefaultMaxSleeperWeight)
        {
            if (float.IsNaN(raw) || raw < 0) return 0;
            float cap = maxWeight > 0 ? maxWeight : DefaultMaxSleeperWeight;
            return raw > cap ? cap : raw;
        }

        /// <summary>Band → suggested prefab density factor before clamp.</summary>
        public static float BandDensityFactor(string? band)
        {
            switch ((band ?? "").Trim().ToLowerInvariant())
            {
                case "metro": return 1.0f;
                case "large_city": return 0.75f;
                case "town": return 0.45f;
                case "village": return 0.25f;
                case "hamlet": return 0.12f;
                default: return 0.05f;
            }
        }
    }
}
