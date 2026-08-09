using System;
using System.Text;

namespace RealEarth
{
    /// <summary>
    /// P7: CDN / missing-tile fail-closed policy + minimal pack manifest fields.
    /// </summary>
    public static class CdnTilePolicy
    {
        /// <summary>
        /// Whether a download/miss should refuse inventing DEM (always true on product path).
        /// </summary>
        public static bool FailClosedOnMiss(bool failClosedMissingTilesConfig) =>
            failClosedMissingTilesConfig;

        /// <summary>
        /// URL for a tile under base CDN (empty base → no CDN).
        /// </summary>
        public static string? TileUrl(string? cdnBase, int tx, int tz)
        {
            if (string.IsNullOrWhiteSpace(cdnBase)) return null;
            string b = cdnBase!.TrimEnd('/');
            return b + "/tiles/" + tz + "/" + tx + ".rte";
        }

        /// <summary>
        /// Minimal pack manifest JSON fields for audit (resolution, fail-closed, sources).
        /// </summary>
        public static string FormatManifestFields(
            int worldWidth,
            int worldHeight,
            int tileSize,
            int seaLevelGameY,
            bool failClosedMissingTiles,
            string? sourcesNote)
        {
            var sb = new StringBuilder(192);
            sb.Append('{');
            sb.Append("\"schema\":\"realearth.pack.v1\",");
            sb.Append("\"world_width\":").Append(worldWidth).Append(',');
            sb.Append("\"world_height\":").Append(worldHeight).Append(',');
            sb.Append("\"tile_size\":").Append(tileSize).Append(',');
            sb.Append("\"sea_level_game_y\":").Append(seaLevelGameY).Append(',');
            sb.Append("\"fail_closed_missing_tiles\":").Append(failClosedMissingTiles ? "true" : "false").Append(',');
            sb.Append("\"sources_note\":\"").Append(Escape(sourcesNote ?? "")).Append('"');
            sb.Append('}');
            return sb.ToString();
        }

        static string Escape(string s) =>
            (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");
    }
}
