using System;
using System.IO;
using System.Text;

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

                string json = File.ReadAllText(manPath, Encoding.UTF8);
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

                // The runtime maps elevation 1 m = 1 block on every product path, so a
                // pack built at a coarser sample size is vertically exaggerated. The
                // scale is not applied, only surfaced: a silently ignored manifest field
                // is a silent misconfiguration.
                double mpb = ReadJsonDouble(json, "meters_per_block");
                if (!double.IsNaN(mpb) && Math.Abs(mpb - 1.0) > 0.001)
                {
                    ModApi.LogWarn(
                        $"Pack is {mpb} m per block; the runtime renders elevation 1 m = 1 block, " +
                        "so vertical relief is exaggerated by that factor.");
                }

                double west = ReadJsonDouble(json, "west");
                double south = ReadJsonDouble(json, "south");
                double east = ReadJsonDouble(json, "east");
                double north = ReadJsonDouble(json, "north");
                // east!=west: continuous (east>west) or dateline wrap (west>east).
                if (!double.IsNaN(west) && !double.IsNaN(south)
                    && !double.IsNaN(east) && !double.IsNaN(north)
                    && east != west && north > south)
                {
                    cfg.BboxWest = west;
                    cfg.BboxSouth = south;
                    cfg.BboxEast = east;
                    cfg.BboxNorth = north;
                    if (cfg.SpawnLongitude == 0 && cfg.SpawnLatitude == 0)
                    {
                        if (east > west)
                            cfg.DefaultSpawnLon = (west + east) * 0.5;
                        else
                        {
                            // Midpoint along wrapped span (same as LonOffsetFromWest / span).
                            double span = (180.0 - west) + (east - (-180.0));
                            double mid = west + span * 0.5;
                            if (mid > 180.0) mid -= 360.0;
                            cfg.DefaultSpawnLon = mid;
                        }
                        cfg.DefaultSpawnLat = (south + north) * 0.5;
                    }
                }

                ModApi.Log($"Pack manifest: {ww}x{wh} tile={ts} seaY={cfg.SeaLevelGameY} wrap={cfg.EnableLongitudeWrap} bbox={cfg.HasRegionalBbox}");
            }
            catch (Exception ex)
            {
                ModApi.LogWarn("Pack manifest skip", ex);
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
