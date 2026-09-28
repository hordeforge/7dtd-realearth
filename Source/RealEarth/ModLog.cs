using System;
using System.Reflection;
using System.Text;

namespace RealEarth
{
    /// <summary>
    /// The mod log sink: one line per call, prefixed by level, routed to the game
    /// logger when it is resolvable and to stdout otherwise. Split out of the
    /// IModApi entry point so a module can log without depending on the bootstrap
    /// class, and so the entry point reads as wiring only.
    /// </summary>
    internal static class ModLog
    {
        // Lazy-resolved once under a lock: Log is called from the main thread and from
        // async tile-load workers concurrently, and three separate volatile fields plus
        // a "resolved" flag is a check-then-act -- two threads can resolve at once and
        // publish a half-filled set, and a resolution that runs before Assembly-CSharp
        // is loadable latches empty delegates so the mod logs to Console forever. The
        // triple is resolved and published as one immutable object instead.
        sealed class LogMethods
        {
            public readonly MethodInfo? Out;
            public readonly MethodInfo? Warn;
            public readonly MethodInfo? Error;
            public LogMethods(MethodInfo? o, MethodInfo? w, MethodInfo? e)
            {
                Out = o; Warn = w; Error = e;
            }
        }

        static readonly object _logGate = new object();
        static volatile LogMethods? _logMethods;

        enum LogLevel { Info, Warn, Error }

        static void Emit(LogLevel level, string msg)
        {
            // Log text carries pack-sourced strings (place names, bands, paths): strip
            // controls here so no caller can forge or split a server-log line.
            msg = msg == null ? "" : CityMapLabels.StripControlChars(msg);
            string Prefix()
                => level == LogLevel.Error ? "[RealEarth][ERROR] "
                 : level == LogLevel.Warn ? "[RealEarth][WARN] "
                 : "[RealEarth] ";
            try
            {
                // Prefer game logger when present (MethodInfo resolved once; hot-path callers
                // log from budgeted per-chunk/per-tick paths). Game Log.Warning / Log.Error
                // let operators filter RealEarth failures out of the flat game log.
                var methods = _logMethods ?? ResolveLogMethods();
                MethodInfo? m = level == LogLevel.Error ? methods.Error
                    : level == LogLevel.Warn ? methods.Warn
                    : methods.Out;
                if (m != null)
                {
                    m.Invoke(null, new object[] { Prefix() + msg });
                    return;
                }
                if (methods.Out != null)
                {
                    // Host logger has no Warning/Error overload: stay on the game log
                    // channel and let the prefix carry the level.
                    methods.Out.Invoke(null, new object[] { Prefix() + msg });
                    return;
                }
            }
            catch
            {
                // fall through
            }

            try
            {
                Console.WriteLine(Prefix() + msg);
            }
            catch
            {
                // ignore
            }
        }

        /// <summary>
        /// Resolve the host logger overloads once. A miss is NOT cached: Assembly-CSharp
        /// may not be loadable yet on the first log line, and latching an empty set there
        /// would pin every later line to Console output for the process lifetime.
        /// </summary>
        static LogMethods ResolveLogMethods()
        {
            lock (_logGate)
            {
                var cached = _logMethods;
                if (cached != null) return cached;
                var logType = Type.GetType("Log, Assembly-CSharp");
                if (logType == null)
                    return new LogMethods(null, null, null);
                var resolved = new LogMethods(
                    logType.GetMethod("Out", new[] { typeof(string) }),
                    logType.GetMethod("Warning", new[] { typeof(string) }),
                    logType.GetMethod("Error", new[] { typeof(string) }));
                _logMethods = resolved;
                return resolved;
            }
        }

        internal static void Log(string msg) => Emit(LogLevel.Info, msg);
        internal static void LogWarn(string msg) => Emit(LogLevel.Warn, msg);

        /// <summary>
        /// One-line rendering of an exception: type, message, and the stack chain as
        /// " | at Frame" segments, inner exceptions appended as " &lt;-". A raw ToString()
        /// would be folded into an unreadable run by StripControlChars at Emit, and a
        /// multi-line entry would break the server log parser. Use this on paths that
        /// fire once (init, patch install, save/load) where the operator has no
        /// debugger; budgeted per-tick/per-chunk paths keep the compact
        /// "{Type}: {Message}" form so a repeated failure stays one short line.
        /// </summary>
        internal static string Describe(Exception ex)
        {
            if (ex == null) return "(null exception)";
            var sb = new StringBuilder(256);
            for (var e = ex; e != null; e = e.InnerException)
            {
                if (sb.Length > 0) sb.Append(" <- ");
                sb.Append(e.GetType().Name).Append(": ").Append(e.Message);
                string stack = e.StackTrace;
                if (string.IsNullOrEmpty(stack)) continue;
                foreach (string raw in stack.Split('\n'))
                {
                    string frame = raw.Trim();
                    if (frame.Length > 0) sb.Append(" | ").Append(frame);
                }
            }
            return sb.ToString();
        }

        internal static void LogWarn(string msg, Exception ex) =>
            Emit(LogLevel.Warn, msg + ": " + Describe(ex));
        internal static void LogError(string msg) => Emit(LogLevel.Error, msg);
        internal static void LogError(string msg, Exception ex) =>
            Emit(LogLevel.Error, msg + ": " + Describe(ex));
    }
}
