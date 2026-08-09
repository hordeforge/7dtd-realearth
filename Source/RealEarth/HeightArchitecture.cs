namespace RealEarth
{
    /// <summary>
    /// Height architecture pointer. Runtime: <see cref="EngineHeight.EngineHeightMod"/>.
    /// Stock: YDim=256 / surface ~255 (literals). RealEarth YDim expand (Tools/) raises the ceiling.
    /// .rte stores real meters; inject maps via EngineHeightPolicy (product: 1:1 real height).
    /// </summary>
    public static class HeightArchitecture
    {
        public const int VanillaMaxY = 255;
        public const int VanillaYDim = 256;
        public const int ProposedSectionHeight = 16;
        public const int ProposedMinY = -128;
        /// <summary>Engine-height mod target (Everest + fly-over). See HeightCompress.EngineTargetMaxY.</summary>
        public const int ProposedMaxY = 11000;

        public static int SectionIndex(int y) =>
            y >= 0 ? y / ProposedSectionHeight : (y - (ProposedSectionHeight - 1)) / ProposedSectionHeight;

        public static int SectionBaseY(int sectionIndex) => sectionIndex * ProposedSectionHeight;
    }
}
