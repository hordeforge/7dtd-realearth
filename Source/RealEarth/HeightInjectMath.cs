using System;

namespace RealEarth
{
    /// <summary>
    /// Pure height inject math (no Unity). Unit-testable offline via Python mirrors
    /// and used by ChunkTerrainSampler / ChunkTerrainInject.
    /// </summary>
    public static class HeightInjectMath
    {
        public const int DefaultSeaLevelGameY = 16000;
        public const int DefaultMissingDepthBelowSea = 8;

        /// <summary>1 m ASL → 1 block: gameY = sea + elevM, clamped.
        /// Delegates to the shared MetersToGameY core (oneToOne branch) so the
        /// linear mapping cannot drift between the two entry points.</summary>
        public static int MetersToGameYOneToOne(float elevM, int seaLevelY, int maxY, int minY = 1)
            => HeightCompress.MetersToGameY(elevM, seaLevelY, maxY, minY, oneToOne: true);

        /// <summary>Legacy byte terrain APIs cannot hold Everest; clamp to 1..255.</summary>
        public static byte ToByteHeight(int gameY)
        {
            if (gameY < 1) return 1;
            if (gameY > 255) return 255;
            return (byte)gameY;
        }

        /// <summary>
        /// Missing .rte tile: never invent land peaks. Returns meters ASL for the
        /// ocean-floor placeholder (-depthBelowSea, 8 m by default); the caller maps
        /// that through the sea level to a game Y. Missing-tile policy
        /// (FailClosedMissingTiles) lives in TileSamplePolicy, not here.
        /// </summary>
        public static float MissingTileElevM(int seaLevelY, int depthBelowSea = DefaultMissingDepthBelowSea)
        {
            // elev ASL such that sea + elev ≈ ocean-floor placeholder Y → elev ≈ -depth
            return -Math.Max(0, depthBelowSea);
        }
    }
}
