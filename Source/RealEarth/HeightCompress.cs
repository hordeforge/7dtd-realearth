using System;

namespace RealEarth
{
    /// <summary>
    /// Real meters ASL → game Y. Vanilla path caps at 255 (byte columns).
    /// Engine-height path supports up to <see cref="EngineTargetMaxY"/>
    /// (Everest + fly-over headroom) via <see cref="CompressExpanded"/> / <see cref="MetersToGameY"/>.
    /// </summary>
    public static class HeightCompress
    {
        /// <summary>Mount Everest elevation (m ASL), 1 m ≈ 1 block in one-to-one mode.</summary>
        public const int EverestMetersAsl = 8849;

        /// <summary>Extra meters/blocks of air above Everest for flight / build headroom.</summary>
        public const int FlyOverHeadroomM = 2000;

        /// <summary>
        /// Height-mod ceiling: sea + Everest + fly-over (+ pad to a clean cap).
        /// With 1:1, Everest surface ≈ 8949 (sea 100); ~2 km of air remains above the summit.
        /// 100 + 8849 + 2000 = 10949 → cap 11000.
        /// </summary>
        public const int EngineTargetMaxY =
            HeightInjectMath.DefaultSeaLevelGameY + EverestMetersAsl + FlyOverHeadroomM + 51; // 11000

        public static byte Compress(float elevM, int seaLevelY = 100, int maxY = 250, int minY = 1)
        {
            int y = MetersToGameY(elevM, seaLevelY, Math.Min(maxY, 255), minY, oneToOne: false);
            return (byte)y;
        }

        /// <summary>
        /// Expanded compress (int game Y). Supports maxY up to <see cref="EngineTargetMaxY"/>.
        /// </summary>
        public static int CompressExpanded(float elevM, int seaLevelY = 100, int maxY = EngineTargetMaxY, int minY = 1)
        {
            maxY = Math.Min(Math.Max(maxY, 1), EngineTargetMaxY);
            return MetersToGameY(elevM, seaLevelY, maxY, minY, oneToOne: false);
        }

        /// <summary>
        /// 1 m real ≈ 1 game block: gameY = seaLevelY + elevM (clamped).
        /// Everest ~8849 m → sea+8849 (e.g. 8949 with sea 100); ceiling leaves fly-over room.
        /// </summary>
        public static int MetersToGameYOneToOne(float elevM, int seaLevelY = 100, int maxY = EngineTargetMaxY, int minY = 1)
        {
            maxY = Math.Min(Math.Max(maxY, 1), EngineTargetMaxY);
            return MetersToGameY(elevM, seaLevelY, maxY, minY, oneToOne: true);
        }

        public static int MetersToGameY(
            float elevM,
            int seaLevelY,
            int maxY,
            int minY = 1,
            bool oneToOne = false)
        {
            maxY = Math.Max(minY + 1, maxY);
            double y;

            if (oneToOne)
            {
                // Linear: 0 m ASL → seaLevelY; +1 m → +1 block (true 1:1 vertical intent)
                y = seaLevelY + elevM;
            }
            else if (elevM <= 0)
            {
                double depth = -elevM;
                double shallow = Math.Min(Math.Max(depth, 0), 200) / 200.0;
                double deep = Math.Min(Math.Max(depth - 200, 0), 10_000) / 10_000.0;
                double drop = shallow * 14.0 + deep * (seaLevelY - minY - 14);
                y = seaLevelY - drop;
            }
            else
            {
                // Piecewise relative curve across [seaLevelY..maxY]; the anchors stretch
                // with maxY, so short bands keep the classic shape while tall bands
                // (Everest + fly room) spread over the full ceiling.
                double h = elevM;
                int yLowEnd = seaLevelY + Math.Max(48, maxY / 16);
                int yMidEnd = seaLevelY + Math.Max(148, maxY / 3);
                int yHighEnd = maxY;
                if (h <= 500)
                {
                    double t = h / 500.0;
                    y = seaLevelY + t * (yLowEnd - seaLevelY);
                }
                else if (h <= 3000)
                {
                    double t = (h - 500.0) / 2500.0;
                    y = yLowEnd + t * (yMidEnd - yLowEnd);
                }
                else
                {
                    // 3000 m → Everest (~8850) and above into upper band
                    double t = Math.Min(Math.Max((h - 3000.0) / 6000.0, 0), 1);
                    t = 1.0 - Math.Pow(1.0 - t, 1.4);
                    y = yMidEnd + t * (yHighEnd - yMidEnd);
                }
            }

            if (y < minY) y = minY;
            if (y > maxY) y = maxY;
            return (int)Math.Round(y);
        }
    }
}
