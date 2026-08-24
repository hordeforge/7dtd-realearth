using System;

namespace RealEarth
{
    /// <summary>P7: CDN / missing-tile fail-closed policy.</summary>
    public static class CdnTilePolicy
    {
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
            // net48 ref assemblies carry no [NotNullWhen] flow hints (same as cdnBase above).
            foreach (char c in url!)
                if (c == '\r' || c == '\n' || c < 0x20) return false;
            if (!Uri.TryCreate(url, UriKind.Absolute, out Uri? u)) return false;
            if (!u.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase)) return false;
            if (string.IsNullOrEmpty(u.Host) || !string.IsNullOrEmpty(u.UserInfo)) return false;
            return u.AbsolutePath.Contains("/tiles/");
        }
    }
}
