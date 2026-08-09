using System;

namespace RealEarth
{
    /// <summary>
    /// Pure height inject math (no Unity). Unit-testable offline via Python mirrors
    /// and used by ChunkTerrainSampler / ChunkTerrainInject.
    /// </summary>
    public static class HeightInjectMath
    {
        public const int DefaultSeaLevelGameY = 100;
        public const int DefaultMissingDepthBelowSea = 8;

        /// <summary>1 m ASL → 1 block: gameY = sea + elevM, clamped.</summary>
        public static int MetersToGameYOneToOne(float elevM, int seaLevelY, int maxY, int minY = 1)
        {
            if (maxY < minY + 1) maxY = minY + 1;
            double y = seaLevelY + elevM;
            if (y < minY) return minY;
            if (y > maxY) return maxY;
            return (int)Math.Round(y);
        }

        /// <summary>Legacy byte terrain APIs cannot hold Everest; clamp to 1..255.</summary>
        public static byte ToByteHeight(int gameY)
        {
            if (gameY < 1) return 1;
            if (gameY > 255) return 255;
            return (byte)gameY;
        }

        /// <summary>
        /// Missing .rte tile: never invent land peaks. Fail-closed returns ocean floor
        /// (sea - depth). When failClosed is false, same placeholder (product default
        /// still avoids stock RWG; only logging/severity differs at call site).
        /// </summary>
        public static int MissingTileGameY(int seaLevelY, int depthBelowSea = DefaultMissingDepthBelowSea)
        {
            int y = seaLevelY - Math.Max(0, depthBelowSea);
            return y < 1 ? 1 : y;
        }

        public static float MissingTileElevM(int seaLevelY, int depthBelowSea = DefaultMissingDepthBelowSea)
        {
            // elev ASL such that sea + elev ≈ MissingTileGameY → elev ≈ -depth
            return -Math.Max(0, depthBelowSea);
        }

        /// <summary>True when a sampled elev is usable DEM (not missing-tile placeholder).</summary>
        public static bool IsPresentSample(bool trySampleOk) => trySampleOk;
    }
}
