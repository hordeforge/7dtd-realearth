using System.Threading;

namespace RealEarth
{
    /// <summary>
    /// Cap on repeated failure lines from hot paths (per-tile, per-chunk, per-tick),
    /// where one root cause can fire thousands of times a second.
    /// Over-budget occurrences are counted, never dropped silently: the suppressed
    /// total is printed by `reinject`, so a truncated log cannot be misread as a
    /// failure that stopped happening.
    /// </summary>
    public sealed class LogBudget
    {
        int _remaining;
        long _suppressed;

        public LogBudget(int slots) => _remaining = slots;

        public long Suppressed => Interlocked.Read(ref _suppressed);

        /// <summary>True while budget remains. False afterwards; every refusal is counted.</summary>
        public bool Allow()
        {
            if (Interlocked.Decrement(ref _remaining) >= 0)
                return true;
            Interlocked.Increment(ref _suppressed);
            return false;
        }

        /// <summary>Refill the cap (world load). Keeps the suppressed total: it is process history.</summary>
        public void Reset(int slots) => Interlocked.Exchange(ref _remaining, slots);
    }
}
