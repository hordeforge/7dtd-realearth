using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;

namespace RealEarth
{
    [DataContract]
    public sealed class RealEarthConfig
    {
        /// <summary>Baked = one finite heightmap world; Streamed = sliding window over full Earth (one session).</summary>
        [DataMember] public string MapMode { get; set; } = "Streamed";

        [DataMember] public string TilePackPath { get; set; } = "Data/tiles";
        [DataMember] public int WorldWidth { get; set; } = 40_075_017;
        [DataMember] public int WorldHeight { get; set; } = 20_003_931;
        [DataMember] public int TileSize { get; set; } = 512;
        /// <summary>
        /// Earth .rte tiles kept hot around EACH player (dynamic overlapping bubbles).
        /// TileSize 512 × radius 2 ≈ 1 km view of Earth data, independent of LocalWindowSize.
        /// MP profile may raise radius (see Config/realearth.mp.json).
        /// </summary>
        [DataMember] public int StreamRadiusTiles { get; set; } = 2;
        [DataMember] public int UnloadRadiusTiles { get; set; } = 4;

        /// <summary>
        /// Finite host world edge the engine allocates (not whole Earth, not all "loaded" mesh).
        /// Slides with absolute position. Keep small: 512–1024 is plenty if tiles inject on demand.
        /// Actual drawn/sim chunks are further limited by vanilla view/sim distance (often &lt;&lt; this).
        /// </summary>
        [DataMember] public int LocalWindowSize { get; set; } = 1024;

        /// <summary>
        /// SoloSlide (default for planetary travel): host window recenters on absolute pos.
        /// SharedFixed: freeze window origin (co-located multiplayer combat).
        /// SharedSlide: accepted alias, but currently slides only when solo (player count ≤ 1),
        /// same as SoloSlide; co-located group sliding is not implemented yet.
        /// </summary>
        [DataMember] public string MultiplayerOriginMode { get; set; } = "SoloSlide";

        [DataMember] public bool EnableLongitudeWrap { get; set; } = false;
        [DataMember] public int SeaLevelGameY { get; set; } = 16000;
        [DataMember] public string TileCdnBaseUrl { get; set; } = "";

        /// <summary>Optional spawn override (degrees). 0,0 with UseDefaultSpawn uses DefaultSpawn*.</summary>
        [DataMember] public double SpawnLongitude { get; set; } = 0;
        [DataMember] public double SpawnLatitude { get; set; } = 0;
        [DataMember] public double DefaultSpawnLon { get; set; } = -104.9903; // Denver-ish demo
        [DataMember] public double DefaultSpawnLat { get; set; } = 39.7392;

        /// <summary>Single continuous map: always true for RealEarth product intent.</summary>
        [DataMember] public bool SingleWorldSession { get; set; } = true;

        /// <summary>
        /// Debug: fill FOW for the whole host world extent once after load.
        /// Default false for ship/release profiles (enable in demo configs only).
        /// </summary>
        [DataMember] public bool DebugRevealFullMap { get; set; } = false;

        /// <summary>
        /// Debug: continuously uncover FOW in a radius around the local player (chunk units).
        /// 0 = off (default). Dev may set 128 (≈ 2048 m).
        /// </summary>
        [DataMember] public int DebugMapRevealRadiusChunks { get; set; } = 0;

        /// <summary>
        /// City names on the map: unlock when the player reaches the city edge,
        /// then pin the label at the geographic center (stays on the map).
        /// </summary>
        [DataMember] public bool ShowCityNamesOnMap { get; set; } = true;

        /// <summary>Skip places below this population when discovering (0 = all).</summary>
        [DataMember] public int CityMapMinPopulation { get; set; } = 0;

        /// <summary>Max discovered labels (largest population considered first in catalog).</summary>
        [DataMember] public int CityMapMaxLabels { get; set; } = 250;

        /// <summary>
        /// Multiplier on per-city edge radius (metro ~14 km, town ~2.5 km, …).
        /// 1.0 = default footprints; raise if discovery feels too tight.
        /// </summary>
        [DataMember] public float CityMapDiscoverRadiusScale { get; set; } = 1.0f;

        /// <summary>
        /// When a .rte tile is missing/corrupt: sample as ocean-floor placeholder and count misses.
        /// Height overrides always replace stock RWG while inject is bound; this flag only
        /// controls miss logging (true = log first misses). See TileSamplePolicy.
        /// </summary>
        [DataMember] public bool FailClosedMissingTiles { get; set; } = true;

        /// <summary>
        /// Max surface Y for full solid block+density fill via reflection.
        /// 0 = default 520 (safe). Tall peaks above this use density-full + block crust.
        /// Raise only if you accept gen cost (e.g. 2000); do not set 11000 without a fast path.
        /// </summary>
        [DataMember] public int FullSolidBlockFillMaxSurface { get; set; } = 0;

        /// <summary>
        /// Runtime POI/density stamps near the player from settlements catalog (P6 budget).
        /// </summary>
        [DataMember] public bool EnableRuntimePoiInject { get; set; } = true;

        /// <summary>
        /// Max runtime POI stamps per session (area budget). Values above the hard
        /// budget cap (DensityBudget.DefaultMaxPrefabsPerKm2 = 80) clamp to 80.
        /// </summary>
        [DataMember] public int RuntimePoiMaxPerArea { get; set; } = 80;

        /// <summary>
        /// Height sampling + inject for Streamed packs. Product path is real meters (1 m = 1 block)
        /// after RealEarth YDim expand. Do not use global height compression as the product mode.
        /// </summary>
        [DataMember] public bool EnableEngineHeightMod { get; set; } = true;

        /// <summary>
        /// Opt-in only: if true and the engine is still stock (YDim ≤ 256), compress real meters
        /// into ~0–250 so the world loads without expand. Product default is false: require
        /// YDim expand and keep true elevation. Expand is part of this mod
        /// (Mods/RealEarth/Tools or make engine-expand).
        /// </summary>
        [DataMember] public bool EngineHeightStockSafe { get; set; } = false;

        /// <summary>
        /// Experimental: hot-patch the YDim expand at runtime via Harmony
        /// transpilers instead of the disk patcher (EngineHeightPatcher.exe).
        /// Only applied when the engine is still stock (YDim=256); a
        /// disk-patched install is never double-rewritten. Research:
        /// 7dtd-engine-research/docs/hot-patch-height.md. Default false: the
        /// disk patcher stays the product path.
        /// </summary>
        [DataMember] public bool EngineHeightRuntimePatch { get; set; } = false;

        /// <summary>
        /// Target game-Y ceiling for 1:1 mapping (sea + airliner cruise + headroom).
        /// Default 29000: sea(16000) + airliner(12000) + headroom(1000).
        /// </summary>
        [DataMember] public int EngineMaxGameY { get; set; } = 29000;

        /// <summary>
        /// Product default: 1 m real elevation ≈ 1 game block (seaLevelY + elev_m).
        /// Only forced off when EngineHeightStockSafe is opted in on a stock engine.
        /// </summary>
        [DataMember] public bool EngineHeightOneToOne { get; set; } = true;

        /// <summary>
        /// If true, clamp to vanilla ~255. Not a product mode; prefer expand + 1:1.
        /// </summary>
        [DataMember] public bool EngineHeightPreferVanillaCeiling { get; set; } = false;

        /// <summary>
        /// Optional regional pack bbox (degrees). When set, lon/lat maps linearly into
        /// WorldWidth×WorldHeight instead of full-planet equirectangular.
        /// Filled from earth.manifest.json by ModApi.TryApplyPackManifest.
        /// </summary>
        [DataMember] public double BboxWest { get; set; }
        [DataMember] public double BboxSouth { get; set; }
        [DataMember] public double BboxEast { get; set; }
        [DataMember] public double BboxNorth { get; set; }

        public bool HasRegionalBbox =>
            BboxEast > BboxWest && BboxNorth > BboxSouth;

        /// <summary>
        /// Explicit Spawn* when either is non-zero; else DefaultSpawn*.
        /// (Exact lon=0,lat=0 still requires setting DefaultSpawn* to 0,0.)
        /// One copy so init spawn and world-ready respawn cannot drift.
        /// </summary>
        public void ResolveSpawnLonLat(out double lon, out double lat)
        {
            bool explicitSpawn = SpawnLongitude != 0 || SpawnLatitude != 0;
            lon = explicitSpawn ? SpawnLongitude : DefaultSpawnLon;
            lat = explicitSpawn ? SpawnLatitude : DefaultSpawnLat;
        }

        /// <summary>
        /// Startup guard: clamp out-of-range numerics to safe values and collect warnings
        /// for unknown enum-like strings. Runs once at init so bad config fails loud
        /// instead of misbehaving mid-session. Returns one message per issue found.
        /// </summary>
        public IReadOnlyList<string> Validate()
        {
            var warnings = new List<string>();

            if (!MapMode.Equals("Streamed", StringComparison.OrdinalIgnoreCase)
                && !MapMode.Equals("Baked", StringComparison.OrdinalIgnoreCase))
                warnings.Add(
                    $"MapMode '{MapMode}' is not Streamed|Baked; treated as Streamed (anything but Baked).");

            var origin = (MultiplayerOriginMode ?? "").Trim();
            if (!origin.Equals("SoloSlide", StringComparison.OrdinalIgnoreCase)
                && !origin.Equals("SharedFixed", StringComparison.OrdinalIgnoreCase)
                && !origin.Equals("SharedSlide", StringComparison.OrdinalIgnoreCase))
                warnings.Add(
                    $"MultiplayerOriginMode '{MultiplayerOriginMode}' is not " +
                    "SoloSlide|SharedFixed|SharedSlide; unknown modes slide only when clearly solo.");
            if (origin.Equals("SharedSlide", StringComparison.OrdinalIgnoreCase))
                warnings.Add(
                    "MultiplayerOriginMode 'SharedSlide' currently slides only when the player " +
                    "count is 1 (same as SoloSlide); co-located group sliding is not implemented. " +
                    "Use SharedFixed for multiplayer combat coords.");

            if (WorldWidth <= 0)
            {
                WorldWidth = 40_075_017;
                warnings.Add("WorldWidth <= 0; reset to full-planet width.");
            }
            if (WorldHeight <= 0)
            {
                WorldHeight = 20_003_931;
                warnings.Add("WorldHeight <= 0; reset to full-planet height.");
            }
            if (TileSize <= 0)
            {
                TileSize = 512;
                warnings.Add("TileSize <= 0; reset to 512.");
            }
            if (StreamRadiusTiles < 0)
            {
                StreamRadiusTiles = 0;
                warnings.Add("StreamRadiusTiles < 0; reset to 0.");
            }
            if (UnloadRadiusTiles < StreamRadiusTiles)
            {
                UnloadRadiusTiles = StreamRadiusTiles + 1;
                warnings.Add(
                    $"UnloadRadiusTiles must exceed StreamRadiusTiles; reset to {UnloadRadiusTiles}.");
            }
            if (LocalWindowSize <= 0)
            {
                LocalWindowSize = Math.Min(WorldWidth, WorldHeight);
                warnings.Add($"LocalWindowSize <= 0; reset to {LocalWindowSize}.");
            }
            else if (LocalWindowSize < 256)
            {
                warnings.Add(
                    $"LocalWindowSize ({LocalWindowSize}) < 256: the recenter band cannot form " +
                    "(margin would cover the whole window), so origin slides stay off. " +
                    "Raise LocalWindowSize (512-1024 recommended).");
            }
            if (SeaLevelGameY <= 0)
            {
                SeaLevelGameY = 16000;
                warnings.Add("SeaLevelGameY <= 0; reset to 16000.");
            }
            if (EngineMaxGameY <= SeaLevelGameY)
                warnings.Add(
                    $"EngineMaxGameY ({EngineMaxGameY}) <= SeaLevelGameY ({SeaLevelGameY}); " +
                    "height mapping collapses, raise EngineMaxGameY.");

            if (CityMapMinPopulation < 0)
            {
                CityMapMinPopulation = 0;
                warnings.Add("CityMapMinPopulation < 0; reset to 0.");
            }
            if (CityMapMaxLabels < 0)
            {
                CityMapMaxLabels = 250;
                warnings.Add("CityMapMaxLabels < 0; reset to 250.");
            }
            if (CityMapDiscoverRadiusScale <= 0f)
            {
                CityMapDiscoverRadiusScale = 1.0f;
                warnings.Add("CityMapDiscoverRadiusScale <= 0; reset to 1.0.");
            }
            if (RuntimePoiMaxPerArea < 0)
            {
                RuntimePoiMaxPerArea = 80;
                warnings.Add("RuntimePoiMaxPerArea < 0; reset to 80.");
            }
            if (FullSolidBlockFillMaxSurface < 0)
            {
                FullSolidBlockFillMaxSurface = 0;
                warnings.Add("FullSolidBlockFillMaxSurface < 0; reset to 0.");
            }

            if (SpawnLongitude < -180 || SpawnLongitude > 180
                || SpawnLatitude < -90 || SpawnLatitude > 90)
                warnings.Add(
                    $"SpawnLongitude/Latitude ({SpawnLongitude}, {SpawnLatitude}) " +
                    "outside [-180,180] x [-90,90] degrees.");
            if (DefaultSpawnLon < -180 || DefaultSpawnLon > 180
                || DefaultSpawnLat < -90 || DefaultSpawnLat > 90)
                warnings.Add(
                    $"DefaultSpawnLon/Lat ({DefaultSpawnLon}, {DefaultSpawnLat}) " +
                    "outside [-180,180] x [-90,90] degrees.");

            if (!string.IsNullOrWhiteSpace(TileCdnBaseUrl))
            {
                string t = TileCdnBaseUrl.Trim();
                bool hasControl = false;
                foreach (char c in t) if (c == '\r' || c == '\n' || c < 0x20) { hasControl = true; break; }
                if (hasControl)
                    warnings.Add("TileCdnBaseUrl contains control characters; CDN disabled.");
                else if (!Uri.TryCreate(t.TrimEnd('/'), UriKind.Absolute, out Uri? u))
                    warnings.Add($"TileCdnBaseUrl '{TileCdnBaseUrl}' is not a valid absolute URL; CDN disabled.");
                else if (!u.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase))
                    warnings.Add($"TileCdnBaseUrl scheme must be https (got {u.Scheme}); CDN disabled.");
                else if (!string.IsNullOrEmpty(u.UserInfo))
                    warnings.Add("TileCdnBaseUrl must not contain userinfo; CDN disabled.");
            }

            // Cross-field / dependent-configuration guards: a single key is valid on
            // its own but contradictory or inert next to another. Surface these at
            // init so the operator fixes the config instead of getting silent,
            // confusing behavior mid-session.
            if (EngineHeightStockSafe && !EnableEngineHeightMod)
                warnings.Add(
                    "EngineHeightStockSafe=true has no effect unless EnableEngineHeightMod is " +
                    "also true; real-height injection is disabled, so StockSafe is inert.");
            if (EngineHeightStockSafe && EngineHeightOneToOne)
                warnings.Add(
                    "EngineHeightStockSafe and EngineHeightOneToOne are mutually exclusive " +
                    "(compress vs 1 m = 1 block). Runtime forces OneToOne=false under StockSafe; " +
                    "set EngineHeightOneToOne=false to match resolved behavior.");
            if (MapMode.Equals("Baked", StringComparison.OrdinalIgnoreCase) && EnableLongitudeWrap)
                warnings.Add(
                    "EnableLongitudeWrap=true is contradictory with MapMode=Baked: a finite host " +
                    "world cannot wrap at the antimeridian. Disable EnableLongitudeWrap for Baked.");
            if (RuntimePoiMaxPerArea > 80)
                warnings.Add(
                    $"RuntimePoiMaxPerArea ({RuntimePoiMaxPerArea}) exceeds the hard cap " +
                    "(DensityBudget.DefaultMaxPrefabsPerKm2 = 80); clamped at inject time.");

            return warnings;
        }

        public static RealEarthConfig Load(string path)
        {
            if (!File.Exists(path))
            {
                var cfg = new RealEarthConfig();
                try
                {
                    var dir = Path.GetDirectoryName(path);
                    if (!string.IsNullOrEmpty(dir))
                        Directory.CreateDirectory(dir);
                    cfg.Save(path);
                }
                catch
                {
                    // ignore write failures
                }
                return cfg;
            }

            try
            {
                using var fs = File.OpenRead(path);
                var ser = new DataContractJsonSerializer(typeof(RealEarthConfig));
                return ser.ReadObject(fs) as RealEarthConfig ?? new RealEarthConfig();
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException(
                    $"Config '{path}' is not a valid realearth.json ({ex.Message}). " +
                    "Fix or delete the file; mod init aborts until then (no streamer/session).",
                    ex);
            }
        }

        public void Save(string path)
        {
            using var fs = File.Create(path);
            var ser = new DataContractJsonSerializer(typeof(RealEarthConfig));
            ser.WriteObject(fs, this);
        }
    }
}
