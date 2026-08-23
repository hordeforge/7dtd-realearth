using System;
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
        /// SharedSlide: slide only when solo / group co-located (partial).
        /// </summary>
        [DataMember] public string MultiplayerOriginMode { get; set; } = "SoloSlide";

        [DataMember] public bool EnableLongitudeWrap { get; set; } = false;
        /// <summary>Globe overlay (not wired to UI yet). Default off until implemented.</summary>
        [DataMember] public bool EnableGlobeMap { get; set; } = false;
        [DataMember] public int SeaLevelGameY { get; set; } = 100;
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

        /// <summary>Max runtime POI stamps per session (area budget).</summary>
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
        /// Target game-Y ceiling for 1:1 mapping (sea + peak + fly room).
        /// Default 11000: sea(100) + Everest(8849) + headroom.
        /// </summary>
        [DataMember] public int EngineMaxGameY { get; set; } = 11000;

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

            using var fs = File.OpenRead(path);
            var ser = new DataContractJsonSerializer(typeof(RealEarthConfig));
            return ser.ReadObject(fs) as RealEarthConfig ?? new RealEarthConfig();
        }

        public void Save(string path)
        {
            using var fs = File.Create(path);
            var ser = new DataContractJsonSerializer(typeof(RealEarthConfig));
            ser.WriteObject(fs, this);
        }
    }
}
