using System;
using System.IO;
using System.Reflection;
using System.Text;

namespace RealEarth
{
    /// <summary>
    /// Game loads every public type implementing IModApi from mod DLLs.
    /// Signature for this install: void InitMod(Mod _modInstance).
    /// </summary>
    public class ModApi : IModApi
    {
        // These are read by the chunk-generation thread and the async tile-load workers,
        // not just by the init thread, so each one is a volatile backing field. A plain
        // auto-property lets a worker read a stale reference across a re-init (old
        // Streamer, previous world's Config) and, because Config's fields are clamped
        // in place during init, lets it read a half-applied one. Config is assigned only
        // after every in-place mutation below has run, so a reader never sees a config
        // that is still being rewritten.
        static volatile string _modPath = "";
        static volatile RealEarthConfig? _config = new RealEarthConfig();
        static volatile TileStreamer? _streamer;
        static volatile EarthCoords? _coords = new EarthCoords();
        static volatile WorldSession? _session;
        static volatile Mod? _modInstance;

        public static string ModPath { get => _modPath; private set => _modPath = value; }
        public static RealEarthConfig Config { get => _config!; private set => _config = value; }
        public static TileStreamer? Streamer { get => _streamer; private set => _streamer = value; }
        public static EarthCoords Coords { get => _coords!; private set => _coords = value; }
        public static WorldSession? Session { get => _session; private set => _session = value; }
        public static Mod? ModInstance { get => _modInstance; private set => _modInstance = value; }

        public void InitMod(Mod _modInstance)
        {
            ModInstance = _modInstance;
            try
            {
                ModPath = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? "";
                if (string.IsNullOrEmpty(ModPath) && _modInstance != null)
                {
                    // Fallback: Mod.Path when available via reflection
                    try
                    {
                        var p = _modInstance.GetType().GetProperty("Path")
                            ?? _modInstance.GetType().GetProperty("ModPath");
                        if (p != null)
                            ModPath = p.GetValue(_modInstance)?.ToString() ?? ModPath;
                    }
                    catch
                    {
                        // ignore
                    }
                }

                var configPath = Path.Combine(ModPath, "Config", "realearth.json");
                var loadedConfig = RealEarthConfig.Load(configPath);
                // Local until every in-place clamp below has run: Config is read from the
                // chunk-generation thread, so publishing it first would expose a config
                // whose WorldWidth/LocalWindowSize/EngineMaxGameY are still being written.
                RealEarthConfig cfg = loadedConfig.Config;
                if (loadedConfig.SynthesizedDefaults)
                    // Not fatal: a fresh install has no config yet and the defaults
                    // are the shipped profile. But say so, because every value the
                    // session runs is then a default nobody chose.
                    LogWarn(
                        $"config: no realearth.json at {configPath}; running built-in defaults " +
                        "(full-planet Streamed, 1:1 height, 512 tiles, wrap auto). " +
                        (loadedConfig.WriteFailed
                            ? "The default file could NOT be written (permissions or a read-only install); "
                              + "the mod stays unconfigured until one is placed there."
                            : "Edit that file to configure the server."));
                foreach (var key in cfg.FindUnknownMemberNames(configPath))
                    LogWarn($"config: key '{key}' is not a RealEarth config key; it is ignored.");

                var tileRoot = Path.IsPathRooted(cfg.TilePackPath)
                    ? cfg.TilePackPath
                    : Path.Combine(ModPath, cfg.TilePackPath);

                // Regional packs (demo): earth.manifest.json overrides world size so
                // local 0-based .rte tiles sample correctly in Streamed mode.
                // Validate runs after the manifest so wrap auto-enable sees final
                // WorldWidth / regional bbox (not the shipped demo placeholders).
                PackManifest.TryApplyPackManifest(tileRoot, cfg);
                foreach (var warning in cfg.Validate())
                    LogWarn($"config: {warning}");

                // Host canvas cannot exceed pack extent
                if (cfg.LocalWindowSize > cfg.WorldWidth)
                    cfg.LocalWindowSize = cfg.WorldWidth;
                if (cfg.LocalWindowSize > cfg.WorldHeight)
                    cfg.LocalWindowSize = cfg.WorldHeight;

                // Height: product is 1:1 real meters after YDim expand (StockSafe is opt-in only).
                // Runs before publication because Init also clamps EngineMaxGameY and
                // settles the one-to-one flag in place on cfg.
                EngineHeight.EngineHeightMod.Init(cfg);

                // Effective profile after the manifest and the clamps above, so a
                // log read shows what the session actually runs, not the file.
                Log(
                    $"config: mode={cfg.MapMode} world={cfg.WorldWidth}x{cfg.WorldHeight} " +
                    $"tile={cfg.TileSize} window={cfg.LocalWindowSize} " +
                    $"stream={cfg.StreamRadiusTiles}/{cfg.UnloadRadiusTiles} " +
                    $"wrap={(cfg.EnableLongitudeWrap ? "on" : "off")} " +
                    $"regionalBbox={cfg.HasRegionalBbox} " +
                    $"seaY={cfg.SeaLevelGameY} maxY={cfg.EngineMaxGameY} " +
                    $"heightMod={(cfg.EnableEngineHeightMod ? (cfg.EngineHeightStockSafe ? "stocksafe" : "1:1") : "off")} " +
                    $"pack={cfg.TilePackPath}");

                // Build the whole generation of world objects off to the side, then
                // publish them back to back. The chunk-generation thread and the
                // tile-load workers read Config/Coords/Streamer/Session; publishing one
                // at a time let them sample a new Config against the previous world's
                // Session and Streamer.
                var coords = new EarthCoords(cfg.WorldWidth, cfg.WorldHeight, cfg.TileSize);
                // A re-init replaces the streamer. The old one is disposed only after
                // the new generation is published, so no worker can pick up a streamer
                // whose HttpClient and hot set are already released.
                var previousStreamer = Streamer;
                var streamer = new TileStreamer(tileRoot, coords, cfg);
                var session = new WorldSession(coords, cfg);

                Coords = coords;
                Config = cfg;
                Streamer = streamer;
                Session = session;
                // Releases the previous HttpClient connection pool and its
                // ~1.5 MB-per-tile hot set rather than stranding them until process exit.
                previousStreamer?.Dispose();
                // Product runtime hot-patch: when opted in on a stock engine,
                // install the Harmony transpilers now (pre-world) so EngineExpanded
                // below reflects the patched capacity. Disk-patched installs are
                // left untouched (the engine already reports expanded).
                if (Config.EnableEngineHeightMod
                    && Config.EngineHeightRuntimePatch
                    && !EngineHeight.EngineHeightMod.EngineExpanded)
                {
                    TryInstallRuntimePatch();
                }
                // Respect MapMode. Do not auto-promote Baked→Streamed when .rte tiles
                // exist: that overrides a continuous baked world and can inject
                // at the wrong earth origin (water columns, missing land, floating
                // decorations). Tall inject is Streamed when the operator chooses it.
                // Prefer explicit Spawn* when either is non-zero; else DefaultSpawn*.
                Config.ResolveSpawnLonLat(out double spawnLon, out double spawnLat);
                Session.SpawnAtLonLat(spawnLon, spawnLat);

                int yDim = EngineHeight.EngineHeightMod.Probe?.ChunkBlockYDim ?? 256;
                // Runtime-aware: the hot patch (RuntimeYDimTranspiler) rewrites
                // literals at JIT, so the probe still reads 256 on a stock engine
                // while the engine actually runs 32768. Use EngineExpanded (which
                // honors IsActive) for the mode label and the expand guard.
                bool runtimeHotPatch = RuntimeYDimTranspiler.IsActive;
                string heightMode = ExpandProductGuard.DescribeHeightMode(
                    Config.EnableEngineHeightMod,
                    Config.EngineHeightStockSafe,
                    yDim,
                    runtimeHotPatch);
                if (ExpandProductGuard.RequiresExpandForRealHeight(
                        Config.EngineHeightStockSafe,
                        Config.EngineHeightOneToOne,
                        yDim,
                        runtimeHotPatch))
                {
                    LogWarn(
                        "P0 ExpandProductGuard: real-height product path needs YDim expand " +
                        $"(YDim={yDim}, StockSafe=false, runtimeHotPatch={runtimeHotPatch}). " +
                        "Enable EngineHeightRuntimePatch (runtime YDim transpiler).");
                }
                Log(
                    $"RealEarth init OK. mode={Config.MapMode} heightMode={heightMode} " +
                    $"singleWorld={Config.SingleWorldSession} " +
                    $"mpOrigin={Config.MultiplayerOriginMode} " +
                    $"allowSlide={SessionOriginPolicy.AllowOriginSlide(Config.MultiplayerOriginMode, Config.LocalWindowSize, Config.WorldWidth, Config.WorldHeight, 1)} " +
                    $"failClosed={Config.FailClosedMissingTiles} " +
                    $"streamR={Config.StreamRadiusTiles} unloadR={Config.UnloadRadiusTiles} " +
                    $"window={Config.LocalWindowSize} world={Config.WorldWidth}x{Config.WorldHeight} " +
                    $"engineHeight={Config.EnableEngineHeightMod} " +
                    $"expanded={EngineHeight.EngineHeightMod.EngineExpanded} " +
                    $"allocY={EngineHeight.EngineHeightMod.AllocatableColumnMaxY} " +
                    $"stockSafe={Config.EngineHeightStockSafe} " +
                    $"debugFow={Config.DebugRevealFullMap} " +
                    $"tiles={tileRoot} path={ModPath}");
                try
                {
                    HarmonyBootstrap.TryPatch();
                }
                catch (Exception hex)
                {
                    LogWarn("Harmony bootstrap skipped", hex);
                }

                try
                {
                    RuntimeHooks.Apply();
                }
                catch (Exception rex)
                {
                    LogWarn("RuntimeHooks skipped", rex);
                }

                // Fail-closed build guard: hash Assembly-CSharp and compare against
                // the reviewed list; an unknown build (game update) blocks inject
                // unless the operator opts in. Runs after hooks so the log order is
                // init -> hooks -> guard verdict.
                try
                {
                    bool guardOk = BuildGuard.Init(Config.EngineHeightAllowUnknownBuild);
                    if (!guardOk)
                        LogWarn("BuildGuard: inject BLOCKED on unknown Assembly-CSharp build.");
                    RuntimeHooks.EnforceInjectGate();
                }
                catch (Exception gex)
                {
                    LogWarn("BuildGuard skipped", gex);
                }
            }
            catch (Exception ex)
            {
                LogError("RealEarth failed to init", ex);
            }
        }

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

        public static void Log(string msg) => Emit(LogLevel.Info, msg);
        public static void LogWarn(string msg) => Emit(LogLevel.Warn, msg);

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

        public static void LogWarn(string msg, Exception ex) =>
            Emit(LogLevel.Warn, msg + ": " + Describe(ex));

        /// <summary>
        /// Product runtime YDim hot-patch: create the Harmony instance
        /// (same recipe as RuntimeHooks) and install the transpiler set, then
        /// re-init EngineHeightMod so EngineExpanded/allocY reflect IsActive.
        /// </summary>
        static void TryInstallRuntimePatch()
        {
            try
            {
                var harmonyType = EngineReflection.FindType("HarmonyLib.Harmony", "0Harmony");
                if (harmonyType == null)
                {
                    LogWarn("RuntimeYDimTranspiler: 0Harmony not loaded yet; hot patch deferred to RuntimeHooks.");
                    return;
                }
                var harmony = Activator.CreateInstance(harmonyType, "com.realearth.7dtd.runtimeydim");
                if (harmony == null)
                    return;
                RuntimeYDimTranspiler.TryInstall(harmony);
                if (RuntimeYDimTranspiler.IsActive)
                {
                    // Re-evaluate the engine-height policy against the patched capacity.
                    EngineHeight.EngineHeightMod.Init(Config);
                    Log("RuntimeYDimTranspiler: engine treated as expanded (hot patch ACTIVE).");
                }
            }
            catch (Exception ex)
            {
                LogWarn("RuntimeYDimTranspiler install failed", ex);
            }
        }
        public static void LogError(string msg) => Emit(LogLevel.Error, msg);
        public static void LogError(string msg, Exception ex) =>
            Emit(LogLevel.Error, msg + ": " + Describe(ex));
    }
}
