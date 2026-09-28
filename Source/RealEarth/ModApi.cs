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
        public static string ModPath { get; private set; } = "";
        public static RealEarthConfig Config { get; private set; } = new RealEarthConfig();
        public static TileStreamer? Streamer { get; private set; }
        public static EarthCoords Coords { get; private set; } = new EarthCoords();
        public static WorldSession? Session { get; private set; }
        public static Mod? ModInstance { get; private set; }

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
                Config = RealEarthConfig.Load(configPath);
                foreach (var key in Config.FindUnknownMemberNames(configPath))
                    LogWarn($"config: key '{key}' is not a RealEarth config key; it is ignored.");

                var tileRoot = Path.IsPathRooted(Config.TilePackPath)
                    ? Config.TilePackPath
                    : Path.Combine(ModPath, Config.TilePackPath);

                // Regional packs (demo): earth.manifest.json overrides world size so
                // local 0-based .rte tiles sample correctly in Streamed mode.
                // Validate runs after the manifest so wrap auto-enable sees final
                // WorldWidth / regional bbox (not the shipped demo placeholders).
                PackManifest.TryApplyPackManifest(tileRoot, Config);
                foreach (var warning in Config.Validate())
                    LogWarn($"config: {warning}");

                // Effective profile after the manifest and the clamps above, so a
                // log read shows what the session actually runs, not the file.
                Log(
                    $"config: mode={Config.MapMode} world={Config.WorldWidth}x{Config.WorldHeight} " +
                    $"tile={Config.TileSize} window={Config.LocalWindowSize} " +
                    $"stream={Config.StreamRadiusTiles}/{Config.UnloadRadiusTiles} " +
                    $"wrap={(Config.EnableLongitudeWrap ? "on" : "off")} " +
                    $"regionalBbox={Config.HasRegionalBbox} " +
                    $"seaY={Config.SeaLevelGameY} maxY={Config.EngineMaxGameY} " +
                    $"heightMod={(Config.EnableEngineHeightMod ? (Config.EngineHeightStockSafe ? "stocksafe" : "1:1") : "off")} " +
                    $"pack={Config.TilePackPath}");

                Coords = new EarthCoords(Config.WorldWidth, Config.WorldHeight, Config.TileSize);
                // Host canvas cannot exceed pack extent
                if (Config.LocalWindowSize > Config.WorldWidth)
                    Config.LocalWindowSize = Config.WorldWidth;
                if (Config.LocalWindowSize > Config.WorldHeight)
                    Config.LocalWindowSize = Config.WorldHeight;

                // A re-init replaces the streamer: dispose the old one so its
                // HttpClient connection pool and decoded hot set are released
                // rather than stranded until process exit.
                Streamer?.Dispose();
                Streamer = new TileStreamer(tileRoot, Coords, Config);
                Session = new WorldSession(Coords, Config);
                // Height: product is 1:1 real meters after YDim expand (StockSafe is opt-in only)
                EngineHeight.EngineHeightMod.Init(Config);
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

        // Lazy-resolved once; volatile because Log is called from the main thread and
        // async tile-load workers concurrently, and a stale flag could pair with a
        // null delegate and permanently fall back to Console output.
        static volatile MethodInfo? _logOut;
        static volatile MethodInfo? _logWarn;
        static volatile MethodInfo? _logError;
        static volatile bool _logResolved;

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
                if (!_logResolved)
                {
                    var logType = Type.GetType("Log, Assembly-CSharp");
                    if (logType != null)
                    {
                        _logOut = logType.GetMethod("Out", new[] { typeof(string) });
                        _logWarn = logType.GetMethod("Warning", new[] { typeof(string) });
                        _logError = logType.GetMethod("Error", new[] { typeof(string) });
                    }
                    _logResolved = true;
                }
                MethodInfo? m = level == LogLevel.Error ? _logError
                    : level == LogLevel.Warn ? _logWarn
                    : _logOut;
                if (m != null)
                {
                    m.Invoke(null, new object[] { Prefix() + msg });
                    return;
                }
                if (_logOut != null)
                {
                    // Host logger has no Warning/Error overload: stay on the game log
                    // channel and let the prefix carry the level.
                    _logOut.Invoke(null, new object[] { Prefix() + msg });
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
