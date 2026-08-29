using System;
using System.Collections.Generic;
using System.Reflection;
using System.Reflection.Emit;
using HarmonyLib;

namespace RealEarth
{
    /// <summary>
    /// Experimental runtime hot-patch of the YDim expand: rewrites the same
    /// inlined Y-bound literals the disk patcher (EngineHeightPatcher.exe)
    /// changes, but via Harmony transpilers at JIT time instead of a file edit.
    ///
    /// Feasibility (see 7dtd-engine-research/docs/hot-patch-height.md): the main
    /// menu JITs none of the 26 Y-bound methods / 6 layer-storage types, so a
    /// transpiler installed from InitMod (pre-world) should catch all sites
    /// before first use. Residual risks: other mods / load order can JIT a site
    /// early (half-patched engine), and there is no --verify equivalent.
    ///
    /// NOT the product default: the disk patcher stays primary. This activates
    /// only when config EngineHeightRuntimePatch=true and the engine is still
    /// stock (YDim=256), so a disk-patched install is never double-rewritten.
    /// </summary>
    public static class RuntimeYDimTranspiler
    {
        public const int TargetYDim = 32768;
        public const int TargetYDimM1 = 32767;
        public const int TargetLayers = TargetYDim / 4; // 8192
        public const int TargetVolumeBits = 16 * 16 * TargetYDim; // 8388608

        /// <summary>True after a full transpiler set installed on a stock engine.</summary>
        public static bool IsActive;

        /// <summary>Count of methods transpiled (diagnostics).</summary>
        public static int PatchCount;

        static readonly object Gate = new object();
        static bool _tried;

        /// <summary>Methods where ldc 256/255 is a vertical bound (mirrors the disk patcher).</summary>
        static readonly HashSet<string> YBoundMethodNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "ResetStability", "ResetStabilityToBottomMost", "GetSameDensityValue",
            "ToTerrain", "RefreshSunlight", "FindSpawnPointAtXZ", "CheckDensities",
            "RepairDensities", "GenerateTerrain", "generateTerrain",
            "GetTerrainHeightAt", "GetTerrainHeightByteAt", "FillOccupiedMap",
            "CopyDecorationsFromPrefab", "GetBlock", "SetBlock", "SetBlockRaw",
            "GetDensity", "SetDensity", "IsWater", "CanMobsSpawnAtPos",
            "CanPlayersSpawnAtPos", "GetLight", "SetLight", "OnBlockAdded",
            "OnBlockRemoved", "LoopOverAllBlocks",
        };

        /// <summary>Types that allocate vertical layer arrays (mirrors the disk patcher).</summary>
        static readonly HashSet<string> LayerStorageTypes = new HashSet<string>(StringComparer.Ordinal)
        {
            "Chunk", "ChunkBlockLayer", "ChunkBlockLayerLegacy", "ChunkBlockChannel",
            "CBCLayer", "UnsafeChunkData`1",
        };

        static bool IsYBoundMethodName(string name)
        {
            if (YBoundMethodNames.Contains(name)) return true;
            if (name.IndexOf("Stability", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (name.IndexOf("Sunlight", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (name.IndexOf("Density", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (name.IndexOf("Terrain", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (name.IndexOf("SpawnPoint", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (name.IndexOf("Light", StringComparison.OrdinalIgnoreCase) >= 0
                && name.IndexOf("Slight", StringComparison.OrdinalIgnoreCase) < 0)
                return true;
            return false;
        }

        static bool IsLayerStorageName(string typeName)
        {
            if (LayerStorageTypes.Contains(typeName)) return true;
            if (typeName.IndexOf("BlockLayer", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (typeName.IndexOf("BlockChannel", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            return false;
        }

        static bool IsBranchCompare(OpCode op)
        {
            return op == OpCodes.Blt || op == OpCodes.Blt_S || op == OpCodes.Ble
                || op == OpCodes.Ble_S || op == OpCodes.Bgt || op == OpCodes.Bgt_S
                || op == OpCodes.Bge || op == OpCodes.Bge_S || op == OpCodes.Blt_Un
                || op == OpCodes.Blt_Un_S || op == OpCodes.Ble_Un || op == OpCodes.Ble_Un_S
                || op == OpCodes.Bgt_Un || op == OpCodes.Bgt_Un_S || op == OpCodes.Bge_Un
                || op == OpCodes.Bge_Un_S;
        }

        static int? ReadLdcI4(OpCode op, object operand)
        {
            if (op == OpCodes.Ldc_I4) return (int)operand;
            if (op == OpCodes.Ldc_I4_S) return (sbyte)operand;
            if (op == OpCodes.Ldc_I4_0) return 0;
            if (op == OpCodes.Ldc_I4_1) return 1;
            if (op == OpCodes.Ldc_I4_2) return 2;
            if (op == OpCodes.Ldc_I4_3) return 3;
            if (op == OpCodes.Ldc_I4_4) return 4;
            if (op == OpCodes.Ldc_I4_5) return 5;
            if (op == OpCodes.Ldc_I4_6) return 6;
            if (op == OpCodes.Ldc_I4_7) return 7;
            if (op == OpCodes.Ldc_I4_8) return 8;
            if (op == OpCodes.Ldc_I4_M1) return -1;
            return null;
        }

        /// <summary>
        /// Harmony transpiler for a Y-bound method. Rewrites the same literals as
        /// the disk patcher (64 -&gt; layers in storage types, 65536 -&gt; volume bits
        /// in WaterDataHandle, 256 -&gt; YDim and 255 -&gt; YMask where the pattern
        /// matches), keyed by the method this transpiler is attached to (injected
        /// __originalMethod), so no cross-method context guessing is needed.
        /// </summary>
        public static IEnumerable<CodeInstruction> Transpile(
            IEnumerable<CodeInstruction> instructions, MethodBase __originalMethod)
        {
            string? typeName = __originalMethod?.DeclaringType?.Name;
            string? methodName = __originalMethod?.Name;
            if (typeName == null || methodName == null)
                return instructions;

            bool isLayerStorage = IsLayerStorageName(typeName);
            bool isYBound = IsYBoundMethodName(methodName);
            bool isWaterDataHandle = typeName == "WaterDataHandle";
            bool isUnsafeChunkData =
                typeName.StartsWith("UnsafeChunkData", StringComparison.Ordinal);
            bool isTerrain = typeName.IndexOf("Terrain", StringComparison.OrdinalIgnoreCase) >= 0;
            bool isProvider = typeName.StartsWith("ChunkProvider", StringComparison.Ordinal)
                || typeName == "World" || typeName == "WorldBlockFiller";

            var list = new List<CodeInstruction>(instructions);
            int rewritten = 0;
            for (int i = 0; i < list.Count; i++)
            {
                var ins = list[i];
                int? val = ReadLdcI4(ins.opcode, ins.operand);
                if (val == null)
                    continue;
                int v = val.Value;
                int? replace = null;

                if (v == 64)
                {
                    if (isLayerStorage)
                        replace = TargetLayers;
                }
                else if (v == 65536 && isWaterDataHandle)
                {
                    replace = TargetVolumeBits;
                }
                else if (v == 256)
                {
                    if (isUnsafeChunkData)
                        continue; // XZ plane stride 16*16, never YDim
                    var next = i + 1 < list.Count ? list[i + 1] : null;
                    if (next == null)
                        continue;
                    if (IsBranchCompare(next.opcode)
                        && (isYBound || isTerrain || isLayerStorage || isProvider))
                    {
                        replace = TargetYDim;
                    }
                }
                else if (v == 255)
                {
                    if (isUnsafeChunkData)
                        continue;
                    var next = i + 1 < list.Count ? list[i + 1] : null;
                    if (next != null && (IsBranchCompare(next.opcode)
                            || next.opcode == OpCodes.Stfld
                            || next.opcode == OpCodes.Ldc_I4_S
                            || next.opcode == OpCodes.Call
                            || next.opcode == OpCodes.Callvirt
                            || next.opcode == OpCodes.Cgt || next.opcode == OpCodes.Clt
                            || next.opcode == OpCodes.Cgt_Un || next.opcode == OpCodes.Clt_Un))
                    {
                        replace = TargetYDimM1;
                    }
                }
                // Intentionally do NOT rewrite 8 (XZ plane bits y<<8) or 256 in
                // UnsafeChunkData Get/Set (XZ strides).

                if (replace == null || replace.Value == v)
                    continue;

                if (ins.opcode == OpCodes.Ldc_I4)
                    ins.operand = replace.Value;
                else if (ins.opcode == OpCodes.Ldc_I4_S)
                    ins.operand = (sbyte)replace.Value;
                list[i] = ins;
                rewritten++;
            }
            if (rewritten > 0 && ConsumeLogBudget())
                ModApi.Log($"RuntimeYDimTranspiler: rewrote {rewritten} literal(s) in {typeName}.{methodName}");
            return list;
        }

        static int _logBudget = 12;
        static bool ConsumeLogBudget() => System.Threading.Interlocked.Decrement(ref _logBudget) >= 0;

        /// <summary>
        /// Enumerate the target types/methods from Assembly-CSharp and attach the
        /// transpiler. Idempotent; only runs once. Uses the direct 0Harmony
        /// reference (the csproj already links Mods/0_TFP_Harmony/0Harmony.dll).
        /// </summary>
        public static void TryInstall(object harmonyInstance)
        {
            lock (Gate)
            {
                if (_tried)
                    return;
                _tried = true;
            }
            try
            {
                if (!(harmonyInstance is Harmony harmony))
                {
                    ModApi.Log("RuntimeYDimTranspiler: harmony instance is not HarmonyLib.Harmony");
                    return;
                }
                var transpilerInfo = typeof(RuntimeYDimTranspiler).GetMethod(
                    nameof(Transpile), BindingFlags.Public | BindingFlags.Static);
                if (transpilerInfo == null)
                    return;
                var transpilerHm = new HarmonyMethod(transpilerInfo);

                var asm = GameAssembly();
                if (asm == null)
                {
                    ModApi.Log("RuntimeYDimTranspiler: Assembly-CSharp not loaded yet");
                    return;
                }

                int attached = 0;
                var seen = new HashSet<string>();
                foreach (var type in asm.GetTypes())
                {
                    if (type == null || type.IsInterface || (type.IsAbstract && !type.IsSealed))
                        continue;
                    string tname = type.Name;
                    bool isLayer = IsLayerStorageName(tname);
                    if (!isLayer && !IsTypeWithYBoundMethods(tname))
                        continue;
                    foreach (var method in type.GetMethods(
                        BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                    {
                        if (method == null || method.IsAbstract || method.ContainsGenericParameters)
                            continue;
                        if (!isLayer && !IsYBoundMethodName(method.Name))
                            continue;
                        string key = type.FullName + "." + method.Name;
                        if (!seen.Add(key))
                            continue;
                        try
                        {
                            harmony.Patch(method, transpiler: transpilerHm);
                            attached++;
                        }
                        catch
                        {
                            // skip methods that cannot be patched
                        }
                    }
                }
                PatchCount = attached;
                IsActive = attached > 0;
                ModApi.Log(
                    $"RuntimeYDimTranspiler: {(IsActive ? "ACTIVE" : "no binds")} " +
                    $"({attached} method transpilers attached; stock engine hot-patch)");
            }
            catch (Exception ex)
            {
                IsActive = false;
                ModApi.LogError($"RuntimeYDimTranspiler: {ex.GetType().Name}: {ex.Message}");
            }
        }

        static bool IsTypeWithYBoundMethods(string typeName)
        {
            if (typeName.IndexOf("Terrain", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (typeName.StartsWith("ChunkProvider", StringComparison.Ordinal)) return true;
            if (typeName == "World" || typeName == "WorldBlockFiller") return true;
            if (typeName == "WaterDataHandle") return true;
            return false;
        }

        static Assembly? GameAssembly()
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                var n = asm.GetName().Name ?? "";
                if (n.Equals("Assembly-CSharp", StringComparison.OrdinalIgnoreCase))
                    return asm;
            }
            return null;
        }
    }
}
