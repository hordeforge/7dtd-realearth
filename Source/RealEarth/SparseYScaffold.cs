using System;

namespace RealEarth
{
    /// <summary>
    /// P8 scaffold: sparse vertical sections (not a full static 0..YDim slab).
    /// Section index math for future dynamic column storage; AbsoluteHeightStore already uses sections.
    /// </summary>
    public static class SparseYScaffold
    {
        public const int DefaultSectionHeight = 16;

        public static int SectionIndex(int gameY, int sectionHeight = DefaultSectionHeight)
        {
            int h = Math.Max(4, sectionHeight);
            if (gameY >= 0) return gameY / h;
            return (gameY - (h - 1)) / h;
        }

        public static void HotSectionRange(
            int surfaceGameY,
            int digMargin,
            int buildMargin,
            int sectionHeight,
            out int minSection,
            out int maxSection)
        {
            int h = Math.Max(4, sectionHeight);
            int y0 = surfaceGameY - Math.Max(0, digMargin);
            int y1 = surfaceGameY + Math.Max(0, buildMargin);
            minSection = SectionIndex(y0, h);
            maxSection = SectionIndex(y1, h);
            if (maxSection < minSection)
            {
                int t = minSection;
                minSection = maxSection;
                maxSection = t;
            }
        }

        /// <summary>Number of hot sections for a surface with margins.</summary>
        public static int HotSectionCount(int surfaceGameY, int digMargin, int buildMargin, int sectionHeight = DefaultSectionHeight)
        {
            HotSectionRange(surfaceGameY, digMargin, buildMargin, sectionHeight, out int a, out int b);
            return b - a + 1;
        }
    }
}
