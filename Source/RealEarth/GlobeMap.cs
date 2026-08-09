using System;

namespace RealEarth
{
    /// <summary>
    /// Globe / world-map state. Actual IMGUI/Unity drawing is hooked when game assemblies exist.
    /// </summary>
    public static class GlobeMapState
    {
        public static bool Enabled { get; set; } = true;
        public static bool Visible { get; set; }
        public static float Zoom { get; set; } = 1f; // 1 = whole Earth, higher = closer
        public static double ViewLon { get; set; }
        public static double ViewLat { get; set; }

        public static void Toggle()
        {
            Visible = !Visible;
        }

        public static void CenterOnPlayer(EarthCoords coords, int worldX, int worldZ)
        {
            coords.BlockToLonLat(worldX, worldZ, out double lon, out double lat);
            ViewLon = lon;
            ViewLat = lat;
        }

        /// <summary>
        /// Project lon/lat to unit sphere for mesh/UI.
        /// </summary>
        public static void LonLatToSphere(double lonDeg, double latDeg, out double x, out double y, out double z)
        {
            double lon = lonDeg * Math.PI / 180.0;
            double lat = latDeg * Math.PI / 180.0;
            double cl = Math.Cos(lat);
            x = cl * Math.Cos(lon);
            y = Math.Sin(lat);
            z = cl * Math.Sin(lon);
        }

        /// <summary>
        /// Equirectangular UV for fallback flat map (wraps U).
        /// </summary>
        public static void LonLatToUv(double lonDeg, double latDeg, out float u, out float v)
        {
            u = (float)((lonDeg + 180.0) / 360.0);
            v = (float)((90.0 - latDeg) / 180.0);
            if (u < 0) u += 1;
            if (u >= 1) u -= 1;
        }
    }

    /// <summary>
    /// Description of what the UI should draw each frame.
    /// Implement with Unity OnGUI / UIToolkit when integrated.
    /// </summary>
    public sealed class GlobeMapFrame
    {
        public double PlayerLon;
        public double PlayerLat;
        public string LocationLabel = "";
        public bool ShowSphere = true;

        public static GlobeMapFrame FromPlayer(EarthCoords coords, int worldX, int worldZ)
        {
            coords.BlockToLonLat(worldX, worldZ, out double lon, out double lat);
            return new GlobeMapFrame
            {
                PlayerLon = lon,
                PlayerLat = lat,
                LocationLabel = $"{lat:0.000}°, {lon:0.000}°",
                ShowSphere = GlobeMapState.Enabled,
            };
        }
    }
}
