using System;
using System.Reflection;

namespace RealEarth.EngineHeight
{
    /// <summary>
    /// Reads vanilla vertical world constants from Assembly-CSharp (3.0.x WorldConstants).
    /// Values are compile-time literals (inlined as ldc in IL) so they cannot simply be
    /// rewritten via Field.SetValue, so expanding them needs selective IL/transpilers or a fork.
    /// </summary>
    public sealed class WorldConstantsProbe
    {
        public int ChunkBlockYDim { get; private set; } = 256;
        public int ChunkBlockYPow { get; private set; } = 8;
        public int ChunkBlockLayers { get; private set; } = 64;
        public int ChunkBlockLayerHeight { get; private set; } = 4;
        public int ChunkDensityYDim { get; private set; } = 256;
        public int CMaxHeight { get; private set; } = 255;
        public bool Probed { get; private set; }
        public string SourceType { get; private set; } = "defaults";

        /// <summary>Vanilla playable max surface Y (inclusive).</summary>
        public int VanillaMaxSurfaceY => Math.Max(0, Math.Min(CMaxHeight, ChunkBlockYDim - 1));

        public static WorldConstantsProbe Probe()
        {
            var p = new WorldConstantsProbe();
            try
            {
                var t = EngineReflection.FindType("WorldConstants");
                if (t != null)
                {
                    p.SourceType = t.FullName ?? "WorldConstants";
                    p.ChunkBlockYDim = ReadInt(t, "ChunkBlockYDim", p.ChunkBlockYDim);
                    p.ChunkBlockYPow = ReadInt(t, "ChunkBlockYPow", p.ChunkBlockYPow);
                    p.ChunkBlockLayers = ReadInt(t, "ChunkBlockLayers", p.ChunkBlockLayers);
                    p.ChunkBlockLayerHeight = ReadInt(t, "ChunkBlockLayerHeight", p.ChunkBlockLayerHeight);
                    p.ChunkDensityYDim = ReadInt(t, "ChunkDensityYDim", p.ChunkDensityYDim);
                    p.Probed = true;
                }
                var raw = EngineReflection.FindType("ChunkProviderGenerateWorldFromRaw");
                if (raw != null)
                    p.CMaxHeight = ReadInt(raw, "cMaxHeight", p.CMaxHeight);
            }
            catch (Exception ex)
            {
                ModApi.LogError($"WorldConstantsProbe: {ex.Message}");
            }
            return p;
        }

        public string Describe() =>
            $"YDim={ChunkBlockYDim} YPow={ChunkBlockYPow} layers={ChunkBlockLayers}x{ChunkBlockLayerHeight} " +
            $"densityY={ChunkDensityYDim} cMaxHeight={CMaxHeight} src={SourceType} " +
            $"(literals: runtime SetValue cannot raise ceiling)";

        static int ReadInt(Type t, string name, int fallback)
        {
            var f = t.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
            if (f == null) return fallback;
            try
            {
                object? v = f.IsLiteral ? f.GetRawConstantValue() : f.GetValue(null);
                return Convert.ToInt32(v);
            }
            catch
            {
                return fallback;
            }
        }
    }
}
