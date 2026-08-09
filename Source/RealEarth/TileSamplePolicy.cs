using System;

namespace RealEarth
{
    /// <summary>
    /// Fail-closed sampling policy for missing/corrupt Earth tiles.
    /// Pure counters + decisions; streamer still owns IO.
    /// </summary>
    public static class TileSamplePolicy
    {
        static long _missingHits;
        static long _presentHits;
        static int _logBudget = 12;

        public static long MissingTileHits => _missingHits;
        public static long PresentTileHits => _presentHits;

        public static void ResetCounters()
        {
            _missingHits = 0;
            _presentHits = 0;
            _logBudget = 12;
        }

        /// <summary>
        /// Resolve elev meters after TrySample. On miss: count + ocean elev placeholder.
        /// Height overrides always replace stock RWG when inject is bound; FailClosedMissingTiles
        /// does not re-enable vanilla hills (only affects logging severity). True passthrough
        /// requires inject unbound.
        /// Returns true if DEM was present.
        /// </summary>
        public static bool ResolveElev(
            bool sampleOk,
            float sampledElevM,
            RealEarthConfig? cfg,
            out float elevM,
            out bool usedFailClosedPlaceholder)
        {
            if (sampleOk)
            {
                _presentHits++;
                elevM = sampledElevM;
                usedFailClosedPlaceholder = false;
                return true;
            }

            _missingHits++;
            usedFailClosedPlaceholder = true;
            // Product always uses ocean placeholder on miss (never invent stock RWG peaks).
            // FailClosedMissingTiles=false only reduces log noise; elev is still ocean.
            bool failClosed = cfg == null || cfg.FailClosedMissingTiles;
            int sea = cfg?.SeaLevelGameY ?? HeightInjectMath.DefaultSeaLevelGameY;
            elevM = HeightInjectMath.MissingTileElevM(sea);
            if (failClosed && _logBudget > 0)
            {
                _logBudget--;
                try
                {
                    ModApi.Log(
                        $"TileSamplePolicy: missing tile sample (failClosed={failClosed}) " +
                        $"misses={_missingHits} elevPlaceholder={elevM}");
                }
                catch
                {
                    // ModApi may be null in offline unit contexts
                }
            }
            return false;
        }

        public static int ElevToGameYInt(float elevM, RealEarthConfig? cfg)
        {
            int sea = cfg?.SeaLevelGameY ?? HeightInjectMath.DefaultSeaLevelGameY;
            int maxY = cfg != null && cfg.EngineMaxGameY > 0
                ? cfg.EngineMaxGameY
                : HeightCompress.EngineTargetMaxY;
            // Cap to engine-allocatable Y so callers never advertise Everest on stock YDim.
            int cap = EngineHeight.EngineHeightMod.AllocatableColumnMaxY;
            if (cap > 0 && maxY > cap)
                maxY = cap;
            return HeightInjectMath.MetersToGameYOneToOne(elevM, sea, maxY);
        }
    }
}
