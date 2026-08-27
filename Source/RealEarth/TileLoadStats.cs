using System.Threading;

namespace RealEarth
{
    /// <summary>
    /// Process-lifetime tile load counters (disk vs CDN, ok vs fail).
    /// Interlocked increments: loads run on async workers, the gen thread
    /// (sync path), and the main thread concurrently. Surfaces via
    /// InjectPatchStats.FormatSummary / reinject console command so "is my
    /// CDN failing?" is one command, not a log grep.
    /// </summary>
    public static class TileLoadStats
    {
        static long _diskOk;
        static long _diskFail;
        static long _cdnOk;
        static long _cdnFail;
        static long _existsErrors;
        static long _badPayloads;

        public static long DiskOk => Interlocked.Read(ref _diskOk);
        public static long DiskFail => Interlocked.Read(ref _diskFail);
        public static long CdnOk => Interlocked.Read(ref _cdnOk);
        public static long CdnFail => Interlocked.Read(ref _cdnFail);
        /// <summary>File.Exists probes that threw (tile root unreadable: permissions,
        /// mount gone). Any nonzero value means the streamer is blind, not missing tiles.</summary>
        public static long ExistsErrors => Interlocked.Read(ref _existsErrors);
        /// <summary>Fetched payloads rejected (magic/size): CDN serving wrong content.</summary>
        public static long BadPayloads => Interlocked.Read(ref _badPayloads);

        public static void AddDiskOk() => Interlocked.Increment(ref _diskOk);
        public static void AddDiskFail() => Interlocked.Increment(ref _diskFail);
        public static void AddCdnOk() => Interlocked.Increment(ref _cdnOk);
        public static void AddCdnFail() => Interlocked.Increment(ref _cdnFail);
        public static void AddExistsError() => Interlocked.Increment(ref _existsErrors);
        public static void AddBadPayload() => Interlocked.Increment(ref _badPayloads);

        public static string FormatSummary() =>
            $"tiles(disk={DiskOk}/{DiskFail} cdn={CdnOk}/{CdnFail} " +
            $"badPayload={BadPayloads} existsErr={ExistsErrors})";
    }
}
