namespace RealEarth
{
    /// <summary>
    /// P0: product-path rules for YDim expand vs stock-safe compress.
    /// Pure decisions (no Unity) for offline tests and init logging.
    /// </summary>
    public static class ExpandProductGuard
    {
        /// <summary>True when engine reports expanded vertical capacity (YDim &gt; 256).</summary>
        public static bool IsExpanded(int chunkBlockYDim) => chunkBlockYDim > 256;

        /// <summary>
        /// Product real-height path requires expand when StockSafe is false.
        /// Returns true if play should refuse tall claims without expand.
        /// </summary>
        public static bool RequiresExpandForRealHeight(bool stockSafe, bool oneToOne, int chunkBlockYDim)
        {
            if (stockSafe) return false; // opt-in compress path
            if (!oneToOne) return false;
            return !IsExpanded(chunkBlockYDim);
        }

        /// <summary>Human-readable mode string for logs / loadgen gates.</summary>
        public static string DescribeHeightMode(bool enableEngineHeight, bool stockSafe, int chunkBlockYDim)
        {
            if (!enableEngineHeight) return "off";
            if (IsExpanded(chunkBlockYDim)) return "ydim-expanded";
            if (stockSafe) return "stock-safe-compress";
            return "needs-expand";
        }
    }
}
