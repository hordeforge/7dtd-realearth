using System;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace RealEarth
{
    /// <summary>
    /// Decoder for offline .rte tiles produced by tools/realearth.
    /// Layout must stay in sync with tools/realearth/tile_format.py
    /// </summary>
    public sealed class RteTile
    {
        public int TileX { get; private set; }
        public int TileZ { get; private set; }
        public int Width { get; private set; }
        public int Height { get; private set; }
        public float[] ElevationM { get; private set; } = Array.Empty<float>();
        public byte[]? Landcover { get; private set; }
        public byte[]? Population { get; private set; }
        public string PoiJson { get; private set; } = "";

        const int ElevOffsetM = 11_000;
        const ushort FlagPop = 1 << 0;
        const ushort FlagLc = 1 << 1;
        const ushort FlagPoi = 1 << 2;

        public static RteTile Load(string path)
        {
            var data = File.ReadAllBytes(path);
            return Decode(data);
        }

        public static RteTile Decode(byte[] data)
        {
            using var ms = new MemoryStream(data);
            using var br = new BinaryReader(ms);
            var magic = br.ReadBytes(4);
            if (magic.Length != 4 || magic[0] != (byte)'R' || magic[1] != (byte)'T'
                || magic[2] != (byte)'E' || magic[3] != (byte)'1')
            {
                throw new InvalidDataException("Not an RTE1 tile");
            }

            int tx = br.ReadInt32();
            int tz = br.ReadInt32();
            ushort ver = br.ReadUInt16();
            ushort flags = br.ReadUInt16();
            int w = br.ReadInt32();
            int h = br.ReadInt32();
            br.ReadInt32(); // reserved

            int elevLen = br.ReadInt32();
            byte[] elevZ = br.ReadBytes(elevLen);
            byte[] elevRaw = Inflate(elevZ);
            if (elevRaw.Length != w * h * 2)
                throw new InvalidDataException("elevation size mismatch");

            var elev = new float[w * h];
            for (int i = 0; i < elev.Length; i++)
            {
                ushort u = (ushort)(elevRaw[i * 2] | (elevRaw[i * 2 + 1] << 8));
                elev[i] = u - ElevOffsetM;
            }

            byte[]? lc = null;
            byte[]? pop = null;
            string poi = "";

            if ((flags & FlagLc) != 0)
            {
                int n = br.ReadInt32();
                lc = Inflate(br.ReadBytes(n));
            }
            if ((flags & FlagPop) != 0)
            {
                int n = br.ReadInt32();
                pop = Inflate(br.ReadBytes(n));
            }
            if ((flags & FlagPoi) != 0 && ms.Position < ms.Length)
            {
                int n = br.ReadInt32();
                poi = Encoding.UTF8.GetString(br.ReadBytes(n));
            }

            return new RteTile
            {
                TileX = tx,
                TileZ = tz,
                Width = w,
                Height = h,
                ElevationM = elev,
                Landcover = lc,
                Population = pop,
                PoiJson = poi,
            };
        }

        public float ElevationAt(int localX, int localZ)
        {
            if (localX < 0 || localZ < 0 || localX >= Width || localZ >= Height)
                return 0f;
            return ElevationM[localZ * Width + localX];
        }

        public byte PopulationAt(int localX, int localZ)
        {
            if (Population == null) return 0;
            if (localX < 0 || localZ < 0 || localX >= Width || localZ >= Height)
                return 0;
            return Population[localZ * Width + localX];
        }

        public byte LandcoverAt(int localX, int localZ)
        {
            if (Landcover == null) return 255;
            if (localX < 0 || localZ < 0 || localX >= Width || localZ >= Height)
                return 255;
            return Landcover[localZ * Width + localX];
        }

        static byte[] Inflate(byte[] zlibData)
        {
            // Python zlib.compress → zlib wrapper (CMF/FLG). DeflateStream wants raw deflate
            // or GZip. Use raw after skipping 2-byte zlib header and 4-byte adler footer.
            if (zlibData.Length < 6)
                throw new InvalidDataException("zlib payload too short");
            using var input = new MemoryStream(zlibData, 2, zlibData.Length - 6);
            using var def = new DeflateStream(input, CompressionMode.Decompress);
            using var output = new MemoryStream();
            def.CopyTo(output);
            return output.ToArray();
        }
    }
}
