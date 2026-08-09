using System;

namespace RealEarth.EngineHeight
{
    /// <summary>
    /// Vertical scale policy.
    /// Product: 1 m ≈ 1 block (real elevation) up to MaxGameY after YDim expand.
    /// Opt-in stock-safe: compress real meters into ~0–250 only when EngineHeightStockSafe is set.
    /// </summary>
    public sealed class EngineHeightPolicy
    {
        public WorldConstantsProbe Probe { get; }
        public bool Enabled { get; }
        public int MaxGameY { get; }
        public int SeaLevelGameY { get; }
        public bool OneToOne { get; }
        public bool StockSafeMode { get; }
        public int VanillaCap => Probe.VanillaMaxSurfaceY;

        public EngineHeightPolicy(WorldConstantsProbe probe, RealEarthConfig cfg)
        {
            Probe = probe ?? WorldConstantsProbe.Probe();
            Enabled = cfg.EnableEngineHeightMod;
            SeaLevelGameY = cfg.SeaLevelGameY;

            bool expanded = Probe.ChunkBlockYDim > 256;
            // Compress only when the operator opts into StockSafe on a stock engine.
            StockSafeMode = !expanded && cfg.EngineHeightStockSafe;
            bool preferVanilla = StockSafeMode || cfg.EngineHeightPreferVanillaCeiling;

            int want = cfg.EngineMaxGameY > 0
                ? cfg.EngineMaxGameY
                : HeightCompress.EngineTargetMaxY;
            want = Math.Min(Math.Max(want, 1), HeightCompress.EngineTargetMaxY);

            if (preferVanilla)
            {
                // Opt-in stock columns (byte heightmap / stock YDim). Not product mode.
                MaxGameY = Math.Min(want, Math.Max(1, Probe.VanillaMaxSurfaceY));
                OneToOne = false;
            }
            else
            {
                MaxGameY = want;
                OneToOne = cfg.EngineHeightOneToOne;
            }
        }

        /// <summary>Map meters ASL → game Y under current policy.</summary>
        public int MapMetersToGameY(float elevM)
        {
            if (OneToOne)
                return HeightCompress.MetersToGameYOneToOne(elevM, SeaLevelGameY, MaxGameY, minY: 1);
            // Stock-safe: compress full Earth range into MaxGameY (typically ~250)
            return HeightCompress.CompressExpanded(elevM, SeaLevelGameY, MaxGameY, minY: 1);
        }

        public int CompressMetersInt(float elevM) => MapMetersToGameY(elevM);

        public byte ToStockByte(float elevM)
        {
            int y = MapMetersToGameY(elevM);
            if (y < 1) return 1;
            if (y > 255) return 255;
            return (byte)y;
        }

        public byte CompressMeters(float elevM) => ToStockByte(elevM);

        public string Describe()
        {
            string mode = !Enabled
                ? "off"
                : StockSafeMode
                    ? "opt-in stock-safe compress (not product)"
                    : OneToOne
                        ? "real height 1:1"
                        : "custom";
            return $"engineHeight={mode} maxGameY={MaxGameY} sea={SeaLevelGameY} " +
                   $"engineYDim={Probe.ChunkBlockYDim} | {Probe.Describe()}";
        }
    }
}
