using System;

namespace RealEarth
{
    /// <summary>
    /// Pure altitude climate math: elev ASL, ISA lapse temperature, and oxygen
    /// saturation used by player-tick hypoxia/cold (reuses drowning oxygen UI).
    /// </summary>
    public static class AltitudeClimate
    {
        /// <summary>ISA troposphere lapse: °C per 1000 m ASL.</summary>
        public const float LapseCPerKm = 6.5f;

        /// <summary>Sea-level reference temperature (°C) when no lat/landcover override.</summary>
        public const float SeaLevelTempC = 15f;

        /// <summary>Hypoxia onset (m ASL): thin air starts to matter.</summary>
        public const int HypoxiaOnsetM = 2500;

        /// <summary>Severe hypoxia (m ASL): commercial airliner cruise band starts.</summary>
        public const int HypoxiaSevereM = 5500;

        /// <summary>Critical hypoxia (m ASL): without oxygen, survival minutes.</summary>
        public const int HypoxiaCriticalM = 8000;

        /// <summary>O2 curve knee (m ASL): oxygen saturation reaches SatFloor there.</summary>
        private const double SatKneeM = 12000.0;

        /// <summary>O2 curve exponent shaping the fall between sea level and the knee.</summary>
        private const double SatExp = 1.4;

        /// <summary>Lowest oxygen saturation the curve returns.</summary>
        private const float SatFloor = 0.35f;

        /// <summary>Cold band onset when ambient temp °C falls below this.</summary>
        public const float ColdOnsetC = 0f;

        /// <summary>Severe cold when ambient temp °C falls below this.</summary>
        public const float ColdSevereC = -20f;

        /// <summary>Soft gap 24: mild heat onset (°C) from desert/hot landcover ambient.</summary>
        public const float HeatOnsetC = 35f;

        /// <summary>Soft gap 24: severe heat when ambient °C rises above this.</summary>
        public const float HeatSevereC = 45f;

        /// <summary>
        /// gameY − seaLevelGameY → meters ASL. Valid only under a 1:1 height
        /// policy; the compressed modes (EngineHeightStockSafe,
        /// EngineHeightPreferVanillaCeiling) saturate gameY at 255, so callers
        /// that need real meters must sample the DEM column instead.
        /// </summary>
        public static int ElevMFromGameY(int gameY, int seaLevelGameY)
            => gameY - seaLevelGameY;

        /// <summary>
        /// Ambient temperature °C from elev ASL (ISA lapse from sea-level base).
        /// Lat/landcover offsets can be added by the caller.
        /// </summary>
        public static float AmbientTempC(int elevMAsl, float seaLevelTempC = SeaLevelTempC)
        {
            float elevKm = elevMAsl / 1000f;
            return seaLevelTempC - (LapseCPerKm * elevKm);
        }

        /// <summary>
        /// Approximate oxygen saturation fraction 0..1 at elev ASL
        /// (rough alveolar O2 curve: ~98% at sea, ~90% at 2500 m, ~75% at 5500 m,
        /// ~55% at 8000 m). Clamped.
        /// </summary>
        public static float OxygenSaturation(int elevMAsl)
        {
            if (elevMAsl <= 0) return 1f;
            // Simple exponential-ish fit: sat = 1 - (elev/SatKneeM)^SatExp, floored at SatFloor.
            double x = elevMAsl / SatKneeM;
            double sat = 1.0 - Math.Pow(x, SatExp);
            if (sat < SatFloor) return SatFloor;
            return (float)sat;
        }

        /// <summary>0=none, 1=mild, 2=severe, 3=critical hypoxia band.</summary>
        public static int HypoxiaBand(int elevMAsl)
        {
            if (elevMAsl >= HypoxiaCriticalM) return 3;
            if (elevMAsl >= HypoxiaSevereM) return 2;
            if (elevMAsl >= HypoxiaOnsetM) return 1;
            return 0;
        }

        /// <summary>0=none, 1=cold, 2=severe cold from ambient °C.</summary>
        public static int ColdBand(float ambientTempC)
        {
            if (ambientTempC <= ColdSevereC) return 2;
            if (ambientTempC <= ColdOnsetC) return 1;
            return 0;
        }

        /// <summary>0=none, 1=heat, 2=severe heat from ambient °C (soft gap 24).</summary>
        public static int HeatBand(float ambientTempC)
        {
            if (ambientTempC >= HeatSevereC) return 2;
            if (ambientTempC >= HeatOnsetC) return 1;
            return 0;
        }

        /// <summary>
        /// Sea-level base temp adjusted by latitude (rough): cooler toward poles.
        /// latDeg in [-90, 90]; equator ~ +seaLevelTempC, poles ~ seaLevelTempC - 30.
        /// </summary>
        public static float SeaLevelTempForLatitude(float latDeg, float seaLevelTempC = SeaLevelTempC)
        {
            float absLat = Math.Abs(latDeg);
            if (absLat > 90f) absLat = 90f;
            return seaLevelTempC - (absLat / 90f) * 30f;
        }

        /// <summary>
        /// Soft gap 24: landcover → ambient °C offset (added after lat+lapse).
        /// Codes match tools/realearth/landcover.py LandCover. Unknown/missing → 0.
        /// </summary>
        public static float LandcoverTempOffsetC(byte landcover)
        {
            switch (landcover)
            {
                case 0: // OCEAN
                case 1: // INLAND_WATER
                    return -2f;
                case 2: // ICE
                case 10: // SNOW
                    return -8f;
                case 3: // BARREN
                    return -1f;
                case 5: // SHRUB
                    return 1f;
                case 11: // DESERT
                    return 6f;
                case 6: // FOREST
                case 7: // WETLAND
                    return -1f;
                case 9: // URBAN
                    return 2f;
                case 4: // GRASS
                case 8: // CROPLAND
                default:
                    return 0f;
            }
        }

        /// <summary>
        /// Ambient °C from elev ASL + lat base + optional landcover offset.
        /// </summary>
        public static float AmbientTempC(
            int elevMAsl, float latDeg, byte landcover, float seaLevelTempC = SeaLevelTempC)
        {
            float seaTemp = SeaLevelTempForLatitude(latDeg, seaLevelTempC);
            return AmbientTempC(elevMAsl, seaTemp) + LandcoverTempOffsetC(landcover);
        }
    }
}
