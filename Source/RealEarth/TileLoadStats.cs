using System.Threading;

namespace RealEarth
{
    /// <summary>
    /// Process-lifetime tile load counters (disk vs CDN, ok vs fail) plus the wall
    /// time each load took, so "is my CDN failing?" and "is it failing slowly?" are
    /// one command, not a log grep. Interlocked: loads run on async workers, the gen
    /// thread (sync path), and the main thread concurrently. Surfaces via
    /// InjectPatchStats.FormatSummary / reinject.
    /// </summary>
    public static class TileLoadStats
    {
        static long _diskOk;
        static long _diskFail;
        static long _cdnOk;
        static long _cdnFail;
        static long _existsErrors;
        static long _badPayloads;
        static long _diskMsTotal;
        static long _diskMsLast;
        static long _diskMsMax;
        static long _cdnMsTotal;
        static long _cdnMsLast;
        static long _cdnMsMax;

        public static long DiskOk => Interlocked.Read(ref _diskOk);
        public static long DiskFail => Interlocked.Read(ref _diskFail);
        public static long CdnOk => Interlocked.Read(ref _cdnOk);
        public static long CdnFail => Interlocked.Read(ref _cdnFail);
        /// <summary>File.Exists probes that threw (tile root unreadable: permissions,
        /// mount gone). Any nonzero value means the streamer is blind, not missing tiles.</summary>
        public static long ExistsErrors => Interlocked.Read(ref _existsErrors);
        /// <summary>Fetched payloads rejected (magic/size): CDN serving wrong content.</summary>
        public static long BadPayloads => Interlocked.Read(ref _badPayloads);

        /// <summary>Wall time of the last successful disk tile load, ms.</summary>
        public static long DiskLastMs => Interlocked.Read(ref _diskMsLast);
        /// <summary>Slowest disk tile load this process, ms.</summary>
        public static long DiskMaxMs => Interlocked.Read(ref _diskMsMax);
        /// <summary>Wall time of the last successful CDN tile fetch+publish, ms.</summary>
        public static long CdnLastMs => Interlocked.Read(ref _cdnMsLast);
        /// <summary>Slowest CDN tile fetch this process, ms.</summary>
        public static long CdnMaxMs => Interlocked.Read(ref _cdnMsMax);

        public static void AddDiskOk(long elapsedMs = 0)
        {
            Interlocked.Increment(ref _diskOk);
            RecordMs(elapsedMs, ref _diskMsTotal, ref _diskMsLast, ref _diskMsMax);
        }

        public static void AddDiskFail() => Interlocked.Increment(ref _diskFail);

        /// <summary>
        /// Zero every counter and the accumulated load times (`reinject reset`).
        /// The suppressed-failure totals live in the log budgets and stay: they are
        /// process history, not a sample window.
        /// </summary>
        public static void Reset()
        {
            Interlocked.Exchange(ref _diskOk, 0);
            Interlocked.Exchange(ref _diskFail, 0);
            Interlocked.Exchange(ref _cdnOk, 0);
            Interlocked.Exchange(ref _cdnFail, 0);
            Interlocked.Exchange(ref _existsErrors, 0);
            Interlocked.Exchange(ref _badPayloads, 0);
            Interlocked.Exchange(ref _diskMsTotal, 0);
            Interlocked.Exchange(ref _diskMsLast, 0);
            Interlocked.Exchange(ref _diskMsMax, 0);
            Interlocked.Exchange(ref _cdnMsTotal, 0);
            Interlocked.Exchange(ref _cdnMsLast, 0);
            Interlocked.Exchange(ref _cdnMsMax, 0);
        }

        public static void AddCdnOk(long elapsedMs = 0)
        {
            Interlocked.Increment(ref _cdnOk);
            RecordMs(elapsedMs, ref _cdnMsTotal, ref _cdnMsLast, ref _cdnMsMax);
        }

        public static void AddCdnFail() => Interlocked.Increment(ref _cdnFail);
        public static void AddExistsError() => Interlocked.Increment(ref _existsErrors);
        public static void AddBadPayload() => Interlocked.Increment(ref _badPayloads);

        /// <summary>
        /// Load failures that were counted but not logged (log budget spent). Nonzero
        /// means the log understates the failure rate, not that the failure stopped.
        /// </summary>
        public static long SuppressedLoadErrors => TileStreamer.LoadErrorBudget.Suppressed;

        static void RecordMs(long elapsedMs, ref long total, ref long last, ref long max)
        {
            if (elapsedMs < 0) elapsedMs = 0;
            Interlocked.Add(ref total, elapsedMs);
            Interlocked.Exchange(ref last, elapsedMs);
            while (true)
            {
                long seen = Interlocked.Read(ref max);
                if (elapsedMs <= seen) return;
                if (Interlocked.CompareExchange(ref max, elapsedMs, seen) == seen) return;
            }
        }

        static string Ms(long total, long count, long last, long max)
        {
            if (count <= 0) return "n/a";
            long avg = total / count;
            return $"{avg}ms avg/{last}ms last/{max}ms max";
        }

        public static string FormatSummary() =>
            $"tiles(disk={DiskOk}/{DiskFail} {Ms(Interlocked.Read(ref _diskMsTotal), DiskOk, DiskLastMs, DiskMaxMs)} " +
            $"cdn={CdnOk}/{CdnFail} {Ms(Interlocked.Read(ref _cdnMsTotal), CdnOk, CdnLastMs, CdnMaxMs)} " +
            $"badPayload={BadPayloads} existsErr={ExistsErrors} suppressedErr={SuppressedLoadErrors})";
    }
}
