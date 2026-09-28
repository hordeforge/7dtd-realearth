using System;
using System.IO;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;

namespace RealEarth
{
    /// <summary>
    /// earth.manifest.json (written by the offline pipeline) read next to tiles/
    /// so Streamed mode uses the pack world size: regional demos carry local tile
    /// indices and a bbox, not full-planet absolute indices.
    /// </summary>
    internal static class PackManifest
    {
        /// <summary>
        /// Overlay the pack manifest onto cfg. Missing or unreadable manifests
        /// leave the shipped config untouched; a parse failure is logged and the
        /// pack is loaded with the config defaults.
        /// </summary>
        internal static void TryApplyPackManifest(string tileRoot, RealEarthConfig cfg)
        {
            try
            {
                var manPath = Path.Combine(tileRoot, "earth.manifest.json");
                if (!File.Exists(manPath))
                    return;

                using var fs = File.OpenRead(manPath);
                var ser = new DataContractJsonSerializer(typeof(EarthManifest));
                var man = ser.ReadObject(fs) as EarthManifest;
                if (man == null)
                    return;

                if (man.WorldWidth > 0) cfg.WorldWidth = man.WorldWidth.Value;
                if (man.WorldHeight > 0) cfg.WorldHeight = man.WorldHeight.Value;
                if (man.TileSize > 0) cfg.TileSize = man.TileSize.Value;
                if (man.SeaLevelGameY > 0) cfg.SeaLevelGameY = man.SeaLevelGameY.Value;

                // Regional packs: disable full-planet wrap (small width)
                if (man.WorldWidth > 0 && man.WorldWidth < 10_000_000)
                    cfg.EnableLongitudeWrap = false;

                ApplyBbox(cfg, man.Bbox);

                ModApi.Log(
                    $"Pack manifest: {man.WorldWidth ?? -1}x{man.WorldHeight ?? -1} " +
                    $"tile={man.TileSize ?? -1} seaY={cfg.SeaLevelGameY} " +
                    $"wrap={cfg.EnableLongitudeWrap} bbox={cfg.HasRegionalBbox}");
            }
            catch (Exception ex)
            {
                ModApi.LogWarn("Pack manifest skip", ex);
            }
        }

        /// <summary>
        /// Copy a complete, non-degenerate bbox onto cfg. east!=west marks a real
        /// span: continuous (east&gt;west) or dateline wrap (west&gt;east).
        /// </summary>
        static void ApplyBbox(RealEarthConfig cfg, EarthManifestBbox? b)
        {
            if (b == null || !b.West.HasValue || !b.South.HasValue
                || !b.East.HasValue || !b.North.HasValue)
                return;
            if (b.East.Value == b.West.Value || b.North.Value <= b.South.Value)
                return;

            cfg.BboxWest = b.West.Value;
            cfg.BboxSouth = b.South.Value;
            cfg.BboxEast = b.East.Value;
            cfg.BboxNorth = b.North.Value;
            if (cfg.SpawnLongitude != 0 || cfg.SpawnLatitude != 0)
                return;

            if (b.East.Value > b.West.Value)
            {
                cfg.DefaultSpawnLon = (b.West.Value + b.East.Value) * 0.5;
            }
            else
            {
                // Midpoint along wrapped span (same as LonOffsetFromWest / span).
                double span = (180.0 - b.West.Value) + (b.East.Value - (-180.0));
                double mid = b.West.Value + span * 0.5;
                if (mid > 180.0) mid -= 360.0;
                cfg.DefaultSpawnLon = mid;
            }
            cfg.DefaultSpawnLat = (b.South.Value + b.North.Value) * 0.5;
        }
    }

    /// <summary>
    /// The manifest fields the mod reads. Nullable so an absent key stays absent:
    /// the shipped config value survives instead of being zeroed.
    /// </summary>
    [DataContract]
    internal sealed class EarthManifest
    {
        [DataMember(Name = "world_width")] public int? WorldWidth { get; set; }
        [DataMember(Name = "world_height")] public int? WorldHeight { get; set; }
        [DataMember(Name = "tile_size")] public int? TileSize { get; set; }
        [DataMember(Name = "sea_level_game_y")] public int? SeaLevelGameY { get; set; }
        [DataMember(Name = "bbox")] public EarthManifestBbox? Bbox { get; set; }
    }

    [DataContract]
    internal sealed class EarthManifestBbox
    {
        [DataMember(Name = "west")] public double? West { get; set; }
        [DataMember(Name = "south")] public double? South { get; set; }
        [DataMember(Name = "east")] public double? East { get; set; }
        [DataMember(Name = "north")] public double? North { get; set; }
    }
}
