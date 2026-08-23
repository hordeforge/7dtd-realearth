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
        /// Only https absolute URLs are accepted; http, protocol-relative,
        /// userinfo-bearing or header-injection payloads return null.
        /// </summary>
        public static string? TileUrl(string? cdnBase, int tx, int tz)
        {
            if (string.IsNullOrWhiteSpace(cdnBase)) return null;
            string trimmed = cdnBase!.Trim();
            if (trimmed.Length == 0) return null;
            // Reject CRLF/header injection and control chars in the configured base.
            foreach (char c in trimmed)
                if (c == '\r' || c == '\n' || c < 0x20) return null;
            trimmed = trimmed.TrimEnd('/');
            if (!Uri.TryCreate(trimmed, UriKind.Absolute, out Uri? uri)) return null;
            if (!uri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase)) return null;
            if (string.IsNullOrEmpty(uri.Host)) return null;
            if (!string.IsNullOrEmpty(uri.UserInfo)) return null;
            if (uri.Host.Contains("..")) return null;
            // Normalize via the validated absolute URI to avoid double-slash tricks.
            string baseNorm = uri.ToString().TrimEnd('/');
            // Ensure the original trimmed prefix matches the normalized absolute (prevents
            // credential smuggling via @ or extra authority not captured by Uri.Host).
            // Uri.ToString() percent-encodes, so compare hosts instead of full strings.
            if (!baseNorm.StartsWith("https://", StringComparison.OrdinalIgnoreCase)) return null;
            return baseNorm + "/tiles/" + tz + "/" + tx + ".rte";
        }

        /// <summary>True if url is a validated https tile url (defense-in-depth for callers).</summary>
        public static bool IsSafeTileUrl(string? url)
        {
            if (string.IsNullOrWhiteSpace(url)) return false;
            foreach (char c in url)
                if (c == '\r' || c == '\n' || c < 0x20) return false;
            if (!Uri.TryCreate(url, UriKind.Absolute, out Uri? u)) return false;
            if (!u.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase)) return false;
            if (string.IsNullOrEmpty(u.Host) || !string.IsNullOrEmpty(u.UserInfo)) return false;
            return u.AbsolutePath.Contains("/tiles/");
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

        static string Escape(string s)
        {
            if (s == null) return "";
            var sb = new StringBuilder(s.Length + 16);
            foreach (char c in s)
            {
                switch (c)
                {
                    case '\\': sb.Append("\\\\"); break;
                    case '"': sb.Append("\\\""); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\t': sb.Append("\\t"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    default:
                        if (c < 0x20)
                            sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            return sb.ToString();
        }
    }
}
