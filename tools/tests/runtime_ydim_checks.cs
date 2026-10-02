using System;
using System.Linq;
using System.Reflection.Emit;
using HarmonyLib;
using RealEarth;

class ChunkBlockChannel
{
    public void fillSameValue() { }
}

class UnsafeChunkData<T> { }
class WaterStorageOwner
{
    public UnsafeChunkData<int> VoxelData = new UnsafeChunkData<int>();
}

namespace RealEarth
{
    // The check drives IL rewriting without the game logger's Unity calls.
    static class ModLog
    {
        public static void Log(string message) { }
        public static void LogError(string context, Exception error) { }
    }
}

class RuntimeHeightChecks
{
    static void Main()
    {
        var generic = typeof(UnsafeChunkData<int>);
        if (!RuntimeYDimTranspiler.PatchTypes(typeof(WaterStorageOwner).Assembly).Contains(generic))
            throw new Exception("Closed generic water storage was not discovered");
        var constructor = generic.GetConstructor(Type.EmptyTypes)!;
        if (constructor.ContainsGenericParameters)
            throw new Exception("Water storage constructor stayed open generic");
        var allocation = RuntimeYDimTranspiler.Transpile(new[] {
            new CodeInstruction(OpCodes.Ldc_I4_S, (sbyte)64),
            new CodeInstruction(OpCodes.Newarr, typeof(int)),
            new CodeInstruction(OpCodes.Ldc_I4, 256),
            new CodeInstruction(OpCodes.Mul),
        }, constructor).ToArray();
        if (allocation[0].opcode != OpCodes.Ldc_I4
            || (int)allocation[0].operand != RuntimeYDimTranspiler.TargetLayers)
            throw new Exception("Closed generic layer allocation did not expand");
        if ((int)allocation[2].operand != 256)
            throw new Exception("The water storage XZ stride changed");
        var method = typeof(ChunkBlockChannel).GetMethod("fillSameValue")!;
        var code = RuntimeYDimTranspiler.Transpile(new[] {
            new CodeInstruction(OpCodes.Ldc_I4_S, (sbyte)63),
            new CodeInstruction(OpCodes.And),
            new CodeInstruction(OpCodes.Ldc_I4_S, (sbyte)63),
            new CodeInstruction(OpCodes.Stloc_0),
            new CodeInstruction(OpCodes.Ldc_I4_S, (sbyte)64),
            new CodeInstruction(OpCodes.Newarr, typeof(byte)),
        }, method).ToArray();
        if ((sbyte)code[0].operand != 63 || code[0].opcode != OpCodes.Ldc_I4_S)
            throw new Exception("The 64-bit shift mask changed");
        if (code[2].opcode != OpCodes.Ldc_I4 || (int)code[2].operand != RuntimeYDimTranspiler.TargetLayers - 1)
            throw new Exception("The descending layer initializer stayed at 63");
        if (code[4].opcode != OpCodes.Ldc_I4 || (int)code[4].operand != RuntimeYDimTranspiler.TargetLayers)
            throw new Exception("The layer allocation did not expand");
        Console.WriteLine("runtime height IL checks passed");
    }
}
