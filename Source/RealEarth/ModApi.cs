using System;
using System.IO;
using System.Reflection;

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

                Config = RealEarthConfig.Load(Path.Combine(ModPath, "Config", "realearth.json"));

                var tileRoot = Path.IsPathRooted(Config.TilePackPath)
                    ? Config.TilePackPath
                    : Path.Combine(ModPath, Config.TilePackPath);

                // Regional packs (demo): earth.manifest.json overrides world size so
                // local 0-based .rte tiles sample correctly in Streamed mode.
                TryApplyPackManifest(tileRoot, Config);

                Coords = new EarthCoords(Config.WorldWidth, Config.WorldHeight, Config.TileSize);
                // Host canvas cannot exceed pack extent
                if (Config.LocalWindowSize > Config.WorldWidth)
                    Config.LocalWindowSize = Config.WorldWidth;
                if (Config.LocalWindowSize > Config.WorldHeight)
                    Config.LocalWindowSize = Config.WorldHeight;

                Streamer = new TileStreamer(tileRoot, Coords, Config);
                Session = new WorldSession(Coords, Config);
                GlobeMapState.Enabled = Config.EnableGlobeMap;
                // Height: product is 1:1 real meters after YDim expand (StockSafe is opt-in only)
                EngineHeight.EngineHeightMod.Init(Config);
                // Only force Streamed for tall inject when the engine was actually expanded
                if (Config.EnableEngineHeightMod
                    && EngineHeight.EngineHeightMod.EngineExpanded
                    && string.Equals(Config.MapMode, "Baked", StringComparison.OrdinalIgnoreCase)
                    && Directory.Exists(Path.Combine(tileRoot, "tiles")))
                {
                    Config.MapMode = "Streamed";
                    Log("EngineHeightMod: Baked→Streamed (expanded engine + .rte tiles for tall inject).");
                    Session = new WorldSession(Coords, Config);
                }
                // Prefer explicit Spawn* when either is non-zero; else DefaultSpawn*.
                // (Exact lon=0,lat=0 still requires setting DefaultSpawn* to 0,0.)
                double spawnLon = (Config.SpawnLongitude != 0 || Config.SpawnLatitude != 0)
                    ? Config.SpawnLongitude
                    : Config.DefaultSpawnLon;
                double spawnLat = (Config.SpawnLongitude != 0 || Config.SpawnLatitude != 0)
                    ? Config.SpawnLatitude
                    : Config.DefaultSpawnLat;
                Session.SpawnAtLonLat(spawnLon, spawnLat);

                int yDim = EngineHeight.EngineHeightMod.Probe?.ChunkBlockYDim ?? 256;
                string heightMode = ExpandProductGuard.DescribeHeightMode(
                    Config.EnableEngineHeightMod,
                    Config.EngineHeightStockSafe,
                    yDim);
                if (ExpandProductGuard.RequiresExpandForRealHeight(
                        Config.EngineHeightStockSafe,
                        Config.EngineHeightOneToOne,
                        yDim))
                {
                    Log(
                        "P0 ExpandProductGuard: real-height product path needs YDim expand " +
                        $"(YDim={yDim}, StockSafe=false). Run make engine-expand.");
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
                    Log($"Harmony bootstrap skipped: {hex.Message}");
                }

                try
                {
                    RuntimeHooks.Apply();
                }
                catch (Exception rex)
                {
                    Log($"RuntimeHooks skipped: {rex.Message}");
                }
            }
            catch (Exception ex)
            {
                Log($"RealEarth failed to init: {ex}");
            }
        }

        static MethodInfo? _logOut;
        static bool _logOutResolved;

        public static void Log(string msg)
        {
            try
            {
                // Prefer game logger when present (MethodInfo resolved once; hot-path callers
                // log from budgeted per-chunk/per-tick paths).
                if (!_logOutResolved)
                {
                    _logOut = Type.GetType("Log, Assembly-CSharp")?.GetMethod("Out", new[] { typeof(string) });
                    _logOutResolved = true;
                }
                if (_logOut != null)
                {
                    _logOut.Invoke(null, new object[] { $"[RealEarth] {msg}" });
                    return;
                }
            }
            catch
            {
                // fall through
            }

            try
            {
                Console.WriteLine($"[RealEarth] {msg}");
            }
            catch
            {
                // ignore
            }
        }

        /// <summary>
        /// Read earth.manifest.json next to tiles/ so Streamed mode uses pack world size
        /// (regional demos use local tile indices, not full-planet absolute indices).
        /// </summary>
        internal static void TryApplyPackManifest(string tileRoot, RealEarthConfig cfg)
        {
            try
            {
                var manPath = Path.Combine(tileRoot, "earth.manifest.json");
                if (!File.Exists(manPath))
                    return;

                string json = File.ReadAllText(manPath);
                // Minimal parse without extra deps (DataContractJsonSerializer needs a type)
                int ww = ReadJsonInt(json, "world_width");
                int wh = ReadJsonInt(json, "world_height");
                int ts = ReadJsonInt(json, "tile_size");
                int sea = ReadJsonInt(json, "sea_level_game_y");
                if (ww > 0) cfg.WorldWidth = ww;
                if (wh > 0) cfg.WorldHeight = wh;
                if (ts > 0) cfg.TileSize = ts;
                if (sea > 0) cfg.SeaLevelGameY = sea;

                // Regional packs: disable full-planet wrap (small width)
                if (ww > 0 && ww < 10_000_000)
                    cfg.EnableLongitudeWrap = false;

                double west = ReadJsonDouble(json, "west");
                double south = ReadJsonDouble(json, "south");
                double east = ReadJsonDouble(json, "east");
                double north = ReadJsonDouble(json, "north");
                if (!double.IsNaN(west) && !double.IsNaN(south)
                    && !double.IsNaN(east) && !double.IsNaN(north)
                    && east > west && north > south)
                {
                    cfg.BboxWest = west;
                    cfg.BboxSouth = south;
                    cfg.BboxEast = east;
                    cfg.BboxNorth = north;
                    if (cfg.SpawnLongitude == 0 && cfg.SpawnLatitude == 0)
                    {
                        cfg.DefaultSpawnLon = (west + east) * 0.5;
                        cfg.DefaultSpawnLat = (south + north) * 0.5;
                    }
                }

                Log($"Pack manifest: {ww}x{wh} tile={ts} seaY={cfg.SeaLevelGameY} wrap={cfg.EnableLongitudeWrap} bbox={cfg.HasRegionalBbox}");
            }
            catch (Exception ex)
            {
                Log($"Pack manifest skip: {ex.Message}");
            }
        }

        static int ReadJsonInt(string json, string key)
        {
            // "key": 123
            string needle = "\"" + key + "\"";
            int i = json.IndexOf(needle, StringComparison.OrdinalIgnoreCase);
            if (i < 0) return -1;
            i = json.IndexOf(':', i);
            if (i < 0) return -1;
            i++;
            while (i < json.Length && (json[i] == ' ' || json[i] == '\t')) i++;
            int j = i;
            while (j < json.Length && (char.IsDigit(json[j]) || json[j] == '-')) j++;
            if (j <= i) return -1;
            if (int.TryParse(json.Substring(i, j - i), out int v))
                return v;
            return -1;
        }

        static double ReadJsonDouble(string json, string key)
        {
            string needle = "\"" + key + "\"";
            int i = json.IndexOf(needle, StringComparison.OrdinalIgnoreCase);
            if (i < 0) return double.NaN;
            i = json.IndexOf(':', i);
            if (i < 0) return double.NaN;
            i++;
            while (i < json.Length && (json[i] == ' ' || json[i] == '\t')) i++;
            int j = i;
            while (j < json.Length && (char.IsDigit(json[j]) || json[j] == '-' || json[j] == '+'
                || json[j] == '.' || json[j] == 'e' || json[j] == 'E'))
                j++;
            if (j <= i) return double.NaN;
            if (double.TryParse(json.Substring(i, j - i),
                    System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture,
                    out double v))
                return v;
            return double.NaN;
        }
    }
}
