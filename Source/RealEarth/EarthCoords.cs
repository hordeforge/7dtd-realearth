using System;

namespace RealEarth
{
    /// <summary>
    /// Equirectangular mapping: block X/Z ↔ lon/lat, tile indices, longitude wrap.
    /// </summary>
    public sealed class EarthCoords
    {
        public int WorldWidth { get; }
        public int WorldHeight { get; }
        public int TileSize { get; }

        public EarthCoords() : this(40_075_017, 20_003_931, 512) { }

        public EarthCoords(int worldWidth, int worldHeight, int tileSize)
        {
            WorldWidth = worldWidth;
            WorldHeight = worldHeight;
            TileSize = tileSize;
        }

        public int WrapX(int x)
        {
            int w = WorldWidth;
            int r = x % w;
            return r < 0 ? r + w : r;
        }

        public int ClampZ(int z)
        {
            if (z < 0) return 0;
            if (z >= WorldHeight) return WorldHeight - 1;
            return z;
        }

        public void BlockToLonLat(int x, int z, out double lon, out double lat)
        {
            x = WrapX(x);
            z = ClampZ(z);
            lon = (x / (double)WorldWidth) * 360.0 - 180.0;
            lat = 90.0 - (z / (double)WorldHeight) * 180.0;
        }

        public void LonLatToBlock(double lon, double lat, out int x, out int z)
        {
            // O(1) wrap into [-180, 180): a large finite input (config typo, bad GPS
            // string) must not spin a decrement loop on the caller's thread; NaN falls
            // through to the cast below and WrapX folds the result into range.
            double t = (lon + 180.0) % 360.0;
            if (t < 0) t += 360.0;
            lon = t - 180.0;
            if (lat < -90.0) lat = -90.0;
            if (lat > 90.0) lat = 90.0;
            x = WrapX((int)((lon + 180.0) / 360.0 * WorldWidth));
            z = ClampZ((int)((90.0 - lat) / 180.0 * WorldHeight));
        }

        public void BlockToTile(int x, int z, out int tx, out int tz)
        {
            x = WrapX(x);
            z = ClampZ(z);
            tx = x / TileSize;
            tz = z / TileSize;
        }

        public int TilesX => (WorldWidth + TileSize - 1) / TileSize;
        public int TilesZ => (WorldHeight + TileSize - 1) / TileSize;
    }
}
