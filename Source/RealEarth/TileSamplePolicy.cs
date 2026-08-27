using System;
using System.Threading;

namespace RealEarth
{
    /// <summary>
    /// Fail-closed sampling policy for missing/corrupt Earth tiles.
    /// Pure counters + decisions; streamer still owns IO.
    /// Counters use Interlocked: height-query hooks run on the main thread AND the
    /// chunk-generation thread, so plain read-modify-write loses updates.
    /// </summary>
    public static class TileSamplePolicy
    {
        static long _missingHits;
        static long _presentHits;
        static int _logBudget = 12;

        public static long MissingTileHits => Volatile.Read(ref _missingHits);
        public static long PresentTileHits => Volatile.Read(ref _presentHits);

        public static void ResetCounters()
        {
            Volatile.Write(ref _missingHits, 0);
            Volatile.Write(ref _presentHits, 0);
            Volatile.Write(ref _logBudget, 12);
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
                Interlocked.Increment(ref _presentHits);
                elevM = sampledElevM;
                usedFailClosedPlaceholder = false;
                return true;
            }

            Interlocked.Increment(ref _missingHits);
            usedFailClosedPlaceholder = true;
            // Product always uses ocean placeholder on miss (never invent stock RWG peaks).
            // FailClosedMissingTiles=false only reduces log noise; elev is still ocean.
            bool failClosed = cfg == null || cfg.FailClosedMissingTiles;
            int sea = cfg?.SeaLevelGameY ?? HeightInjectMath.DefaultSeaLevelGameY;
            elevM = HeightInjectMath.MissingTileElevM(sea);
            if (failClosed && Interlocked.Decrement(ref _logBudget) >= 0)
            {
                try
                {
                    ModApi.LogWarn(
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

        /// <summary>
        /// Map resolved elevation meters to a game Y column value.
        /// allocatableMaxY: engine-allocatable ceiling supplied by the caller
        /// (the engine-height subsystem exposes it) so this policy never reaches
        /// up into that subsystem; 0 disables the cap.
        /// </summary>
        public static int ElevToGameYInt(float elevM, RealEarthConfig? cfg, int allocatableMaxY = 0)
        {
            int sea = cfg?.SeaLevelGameY ?? HeightInjectMath.DefaultSeaLevelGameY;
            int maxY = cfg != null && cfg.EngineMaxGameY > 0
                ? cfg.EngineMaxGameY
                : HeightCompress.EngineTargetMaxY;
            // Cap to engine-allocatable Y so callers never advertise Everest on stock YDim.
            if (allocatableMaxY > 0 && maxY > allocatableMaxY)
                maxY = allocatableMaxY;
            return HeightInjectMath.MetersToGameYOneToOne(elevM, sea, maxY);
        }
    }
}
