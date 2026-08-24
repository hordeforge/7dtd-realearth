using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;

namespace RealEarth.EnginePatcher
{
    /// <summary>
    /// Patches 7DTD Assembly-CSharp.dll so vertical world size supports RealEarth 1:1 heights.
    ///
    /// CRITICAL: stock uses 256 for BOTH:
    ///   - ChunkBlockYDim (vertical blocks per column)
    ///   - ChunkAreaDim (16×16 XZ heightmap / biome / normal maps)
    /// Blind 256→16384 rewrites XZ maps and packing strides, which makes load ~64× slower
    /// and corrupts indexing. This patcher only expands true vertical / layer sites.
    ///
    /// ALWAYS backs up the original DLL. Steam verify restores stock.
    /// Re-run safe: marker + stock backup converge; a re-run never labels an
    /// already-expanded DLL as stock, and heals a marker lost to a mid-run crash.
    /// </summary>
    static class Program
    {
        // Everest 1:1 default: sea(100)+8849+fly ≈ 11000 → next power-of-two YDim.
        // Override with --ydim 512|1024|2048|4096|8192|16384 for lighter machines.
        // Layer counts must be rewritten consistently (alloc + free) or Unity.Collections Free crashes.
        static int TargetYDim = 16384; // 2^14
        static int TargetYPow = 14;
        static int TargetYDimM1 = TargetYDim - 1;
        const int LayerHeight = 4;
        static int TargetLayers = TargetYDim / LayerHeight;
        static int TargetVolumeBits = 16 * 16 * TargetYDim;

        // Types that allocate vertical layer arrays (64 = YDim/LayerHeight).
        static readonly HashSet<string> LayerStorageTypes = new HashSet<string>(StringComparer.Ordinal)
        {
            "Chunk",
            "ChunkBlockLayer",
            "ChunkBlockLayerLegacy",
            "ChunkBlockChannel",
            "CBCLayer",
            "UnsafeChunkData`1",
        };

        // Methods where ldc 256/255 is a vertical bound (not XZ area).
        static readonly HashSet<string> YBoundMethodNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "ResetStability",
            "ResetStabilityToBottomMost",
            "GetSameDensityValue",
            "ToTerrain",
            "RefreshSunlight",
            "FindSpawnPointAtXZ",
            "CheckDensities",
            "RepairDensities",
            "GenerateTerrain",
            "generateTerrain",
            "GetTerrainHeightAt",
            "GetTerrainHeightByteAt",
            "FillOccupiedMap",
            "CopyDecorationsFromPrefab",
            "GetBlock",
            "SetBlock",
            "SetBlockRaw",
            "GetDensity",
            "SetDensity",
            "IsWater",
            "CanMobsSpawnAtPos",
            "CanPlayersSpawnAtPos",
            "GetLight",
            "SetLight",
            "OnBlockAdded",
            "OnBlockRemoved",
            "LoopOverAllBlocks",
        };

        // stfld targets that are XZ maps (size must stay 256 = 16×16).
        static readonly string[] XzMapFieldSnippets =
        {
            "m_HeightMap",
            "m_TerrainHeight",
            "m_Biomes",
            "m_BiomeIntensities",
            "m_NormalX",
            "m_NormalY",
            "m_NormalZ",
            "m_DecoBiomeArray",
            "mapColors",
            "m_bTopSoilBroken",
            "HeightMap",
            "TerrainHeight",
            "Biomes",
            "NormalX",
            "NormalY",
            "NormalZ",
        };

        static int Log2Exact(int v)
        {
            int pow = 0;
            while ((1 << pow) < v) pow++;
            if ((1 << pow) != v)
                throw new ArgumentException("value is not a power of two: " + v);
            return pow;
        }

        static void SetYDim(int yDim)
        {
            // Power-of-two only (bitmasks / YPow)
            if (yDim < 256 || (yDim & (yDim - 1)) != 0)
                throw new ArgumentException("YDim must be power of two >= 256, got " + yDim);
            TargetYDim = yDim;
            // Integer log2: (int)Math.Log(yDim, 2) truncates, so a double result
            // of 13.9999... would desync YPow/masks from the validated YDim.
            TargetYPow = Log2Exact(yDim);
            TargetYDimM1 = yDim - 1;
            TargetLayers = yDim / LayerHeight;
            TargetVolumeBits = 16 * 16 * yDim;
        }

        static int Main(string[] args)
        {
            string? gameDll = null;
            bool dryRun = false;
            bool force = false;
            for (int i = 0; i < args.Length; i++)
            {
                // Unknown flags must hard-fail: a typo'd --dryrun would otherwise
                // be ignored and the patcher would perform a real write.
                if (args[i] == "--dll" && i + 1 < args.Length) gameDll = args[++i];
                else if (args[i] == "--ydim" && i + 1 < args.Length)
                {
                    SetYDim(int.Parse(args[++i]));
                }
                else if (args[i] == "--dry-run") dryRun = true;
                else if (args[i] == "--force") force = true;
                else if (args[i] == "--help" || args[i] == "-h")
                {
                    PrintHelp();
                    return 0;
                }
                else
                {
                    Console.Error.WriteLine(
                        "ERROR: unknown argument: " + args[i] +
                        " (valid: --dll <path> --ydim <n> --dry-run --force)");
                    PrintHelp();
                    return 2;
                }
            }

            if (string.IsNullOrEmpty(gameDll))
            {
                var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                gameDll = Path.Combine(
                    home,
                    ".local/share/Steam/steamapps/common/7 Days To Die/7DaysToDie_Data/Managed/Assembly-CSharp.dll");
            }

            // Explicit null test (not just IsNullOrEmpty): net48 reference
            // assemblies carry no nullable annotations, so only this pattern
            // tells the compiler gameDll is non-null below.
            if (gameDll is null || !File.Exists(gameDll))
            {
                Console.Error.WriteLine("ERROR: Assembly-CSharp.dll not found: " + gameDll);
                Console.Error.WriteLine("Pass --dll /path/to/Assembly-CSharp.dll");
                return 2;
            }

            Console.WriteLine("RealEarth Engine Height Patcher (safe Y-only)");
            Console.WriteLine("  target YDim = {0} (2^{1}), layers = {2} x {3}", TargetYDim, TargetYPow, TargetLayers, LayerHeight);
            Console.WriteLine("  dll = {0}", gameDll);
            Console.WriteLine("  dryRun = {0}", dryRun);

            string bak = gameDll + ".re_stock_bak";
            string marked = gameDll + ".re_height_expanded";

            if (File.Exists(marked) && !force && !dryRun)
            {
                Console.WriteLine("Already patched (marker exists). Use --force to re-apply from backup.");
                if (File.Exists(bak))
                    Console.WriteLine("  stock backup: " + bak);
                return 0;
            }

            string readPath = gameDll;
            if (File.Exists(bak) && force)
            {
                Console.WriteLine("Restoring stock from backup before re-patch...");
                if (!dryRun)
                    File.Copy(bak, gameDll, overwrite: true);
                else
                    readPath = bak; // dry-run: analyze stock backup, do not write
            }
            // No eager backup here. Backup happens after analysis (below), only when real
            // work remains and before any byte is written, so an already-expanded DLL is
            // never copied as "stock" (that would poison engine-restore).

            var resolver = new DefaultAssemblyResolver();
            resolver.AddSearchDirectory(Path.GetDirectoryName(gameDll));
            var rp = new ReaderParameters
            {
                AssemblyResolver = resolver,
                ReadWrite = !dryRun && readPath == gameDll,
                InMemory = dryRun || readPath != gameDll,
            };
            using (var module = ModuleDefinition.ReadModule(readPath, rp))
            {
                int atTarget = 0;
                int constHits = PatchConstantMetadata(module, ref atTarget);
                int ilHits = PatchIlConstants(module);
                Console.WriteLine("  constant table rewrites: {0}", constHits);
                Console.WriteLine("  IL Ldc rewrites: {0}", ilHits);

                if (constHits + ilHits == 0)
                {
                    // Key constants already equal target values → previous expand completed
                    // (e.g. crash between DLL write and marker creation). Converge state
                    // instead of failing: restore the marker so future runs detect it.
                    if (atTarget > 0)
                    {
                        Console.WriteLine("Already at target expand (no further rewrites).");
                        if (!dryRun && !File.Exists(marked))
                        {
                            WriteMarker(marked);
                            Console.WriteLine("Marker restored: " + marked);
                        }
                        return 0;
                    }
                    Console.Error.WriteLine("No patches applied — types/constants not found?");
                    return 3;
                }

                if (!dryRun)
                {
                    // Module changes are in-memory until Write(); gameDll is still the
                    // unmodified input here, so this copy is genuine stock.
                    if (!File.Exists(bak))
                    {
                        File.Copy(gameDll, bak, overwrite: false);
                        Console.WriteLine("Backup written: " + bak);
                    }
                    module.Write();
                    WriteMarker(marked);
                    Console.WriteLine("Patched OK. Marker: " + marked);
                    Console.WriteLine("If the game fails to boot, restore:");
                    Console.WriteLine("  cp -a \"" + bak + "\" \"" + gameDll + "\"");
                    Console.WriteLine("  rm -f \"" + marked + "\"");
                }
                else
                {
                    Console.WriteLine("Dry-run complete (no files written).");
                }
            }

            return 0;
        }

        static void WriteMarker(string marked)
        {
            File.WriteAllText(
                marked,
                "RealEarth engine height expand (safe Y-only)\n" +
                "YDim=" + TargetYDim + "\n" +
                "YPow=" + TargetYPow + "\n" +
                "Layers=" + TargetLayers + "\n" +
                "rules=no-xz-maps,no-ypow-shift,layer-storage,y-bound-methods\n" +
                "utc=" + DateTime.UtcNow.ToString("o") + "\n");
        }

        static void PrintHelp()
        {
            Console.WriteLine(
                "Usage: EngineHeightPatcher [--dll PATH] [--ydim N] [--dry-run] [--force]\n" +
                "\n" +
                "Safe Y-only expand: layer arrays + vertical bounds. Does NOT expand XZ maps.\n" +
                "--ydim: power of two (default 16384 Everest-scale; try 512/1024 for lighter tests).\n");
        }

        static int PatchConstantMetadata(ModuleDefinition module, ref int atTarget)
        {
            int hits = 0;
            var map = new Dictionary<string, int>(StringComparer.Ordinal)
            {
                ["ChunkBlockYDim"] = TargetYDim,
                ["ChunkBlockYPow"] = TargetYPow,
                ["ChunkBlockYDimM1"] = TargetYDimM1,
                ["ChunkBlockYMask"] = TargetYDimM1,
                ["ChunkBlockLayers"] = TargetLayers,
                ["ChunkDensityYDim"] = TargetYDim,
                ["ChunkDensityYPow"] = TargetYPow,
                ["ChunkDensityYMask"] = TargetYDimM1,
                ["cMaxHeight"] = TargetYDimM1,
                // ChunkAreaDim stays 256 (16×16) — do not touch
            };

            foreach (var type in module.Types)
            {
                hits += PatchConstantsOnType(type, map, ref atTarget);
                foreach (var nested in type.NestedTypes)
                    hits += PatchConstantsOnType(nested, map, ref atTarget);
            }
            return hits;
        }

        static int PatchConstantsOnType(TypeDefinition type, Dictionary<string, int> map, ref int atTarget)
        {
            int hits = 0;
            if (!type.Fields.Any(f => map.ContainsKey(f.Name)))
                return 0;

            foreach (var field in type.Fields)
            {
                if (!map.TryGetValue(field.Name, out int newVal))
                    continue;
                if (!field.HasConstant)
                    continue;
                object? cur = field.Constant;
                int oldInt = cur is int i ? i : Convert.ToInt32(cur);
                if (oldInt == newVal)
                {
                    // Already at target: evidence of a previous successful expand.
                    atTarget++;
                    continue;
                }
                Console.WriteLine("  const {0}.{1}: {2} → {3}", type.Name, field.Name, oldInt, newVal);
                field.Constant = newVal;
                hits++;
            }
            return hits;
        }

        static int PatchIlConstants(ModuleDefinition module)
        {
            int hits = 0;
            foreach (var type in AllTypes(module))
            {
                foreach (var method in type.Methods)
                {
                    if (!method.HasBody)
                        continue;
                    // Never touch static ctors (rectCracks[8] etc.)
                    if (method.Name == ".cctor")
                        continue;
                    hits += PatchMethodBody(type, method);
                }
            }
            return hits;
        }

        static IEnumerable<TypeDefinition> AllTypes(ModuleDefinition module)
        {
            foreach (var t in module.Types)
            {
                yield return t;
                foreach (var n in t.NestedTypes)
                    yield return n;
            }
        }

        static int PatchMethodBody(TypeDefinition type, MethodDefinition method)
        {
            int hits = 0;
            var il = method.Body.Instructions;
            for (int i = 0; i < il.Count; i++)
            {
                var ins = il[i];
                int? val = ReadLdcI4(ins);
                if (val == null)
                    continue;

                int v = val.Value;
                int? replace = null;

                if (v == 64)
                {
                    // Layer count: MUST rewrite every 64 in storage types (alloc AND free
                    // sizes). Partial rewrites crash in AllocatorManager.Free.
                    if (IsLayerStorageType(type))
                        replace = TargetLayers;
                }
                else if (v == 65536 && type.Name == "WaterDataHandle")
                {
                    // activeVoxels bit array = full column volume 16*16*YDim
                    replace = TargetVolumeBits;
                }
                else if (v == 256)
                {
                    if (ShouldRewriteYDim256(type, method, il, i))
                        replace = TargetYDim;
                }
                else if (v == 255)
                {
                    if (ShouldRewriteYMask255(type, method, il, i))
                        replace = TargetYDimM1;
                }
                // Intentionally do NOT rewrite 8: packing uses y<<8 for XZ plane bits
                // (XPow+ZPow=8), which is NOT log2(YDim). Rewriting breaks indexing.
                // Do NOT rewrite 256 inside UnsafeChunkData Get/Set: those are XZ plane
                // strides (16*16), not YDim.

                if (replace == null || replace.Value == v)
                    continue;

                WriteLdcI4(ins, replace.Value);
                hits++;
            }
            return hits;
        }

        static bool IsLayerStorageType(TypeDefinition type)
        {
            if (type == null) return false;
            if (LayerStorageTypes.Contains(type.Name)) return true;
            if (type.Name.IndexOf("BlockLayer", StringComparison.OrdinalIgnoreCase) >= 0)
                return true;
            if (type.Name.IndexOf("BlockChannel", StringComparison.OrdinalIgnoreCase) >= 0)
                return true;
            if (type.Name.StartsWith("UnsafeChunkData", StringComparison.Ordinal))
                return true;
            return false;
        }

        /// <summary>
        /// 64 is layer count when used as array length or loop bound over layers.
        /// ChunkBlockChannel..ctor does: ldc 64; ldfld bytesPerVal; mul; newarr — look ahead.
        /// </summary>
        static bool IsLayerArraySite(Mono.Collections.Generic.Collection<Instruction> il, int index)
        {
            if (index + 1 >= il.Count) return false;

            // Look ahead a few ops for newarr / loop compare (ctor multiplies by bytesPerVal first).
            for (int k = index + 1; k < Math.Min(index + 8, il.Count); k++)
            {
                var op = il[k];
                if (op.OpCode == OpCodes.Newarr)
                {
                    var tr = op.Operand as TypeReference;
                    string n = tr?.Name ?? "";
                    // sameValue is Byte[], layers is CBCLayer[]
                    if (n == "Byte" || n == "CBCLayer" || n.IndexOf("Layer", StringComparison.OrdinalIgnoreCase) >= 0
                        || n.IndexOf("Channel", StringComparison.OrdinalIgnoreCase) >= 0)
                        return true;
                    return true;
                }
                if (op.OpCode == OpCodes.Blt || op.OpCode == OpCodes.Blt_S
                    || op.OpCode == OpCodes.Ble || op.OpCode == OpCodes.Ble_S
                    || op.OpCode == OpCodes.Blt_Un || op.OpCode == OpCodes.Blt_Un_S
                    || op.OpCode == OpCodes.Ble_Un || op.OpCode == OpCodes.Ble_Un_S)
                    return true;
                if (op.OpCode == OpCodes.Stfld || op.OpCode == OpCodes.Stsfld)
                {
                    string f = op.Operand?.ToString() ?? "";
                    if (f.IndexOf("Layer", StringComparison.OrdinalIgnoreCase) >= 0
                        || f.IndexOf("sameValue", StringComparison.OrdinalIgnoreCase) >= 0)
                        return true;
                }
                // Stop look-ahead if we leave the local expression (ret / branch elsewhere)
                if (op.OpCode == OpCodes.Ret)
                    break;
            }

            var next = il[index + 1];
            if (next.OpCode == OpCodes.Newobj) return true;
            if (next.OpCode == OpCodes.Ldelem_Ref || next.OpCode == OpCodes.Stelem_Ref)
                return true;
            return false;
        }

        static bool ShouldRewriteYDim256(
            TypeDefinition type,
            MethodDefinition method,
            Mono.Collections.Generic.Collection<Instruction> il,
            int index)
        {
            // UnsafeChunkData packs voxels with 256 = XZ plane size inside each layer.
            if (type.Name.StartsWith("UnsafeChunkData", StringComparison.Ordinal))
                return false;

            // Hard deny: XZ map allocations and I/O sizes
            if (IsXzMapSizeSite(il, index))
                return false;

            // Hard deny: index packing (x + z*16 + y*256) — 256 is XZ plane, not YDim
            if (IsXzPlaneStrideSite(il, index))
                return false;

            var next = index + 1 < il.Count ? il[index + 1] : null;
            if (next == null) return false;

            // Vertical loop / compare bounds in known methods
            if (IsBranchCompare(next) && IsYBoundMethod(method))
                return true;

            // Vector3i(yMax, ...) density checks — first arg 256 as Y
            if (IsYBoundMethod(method) && next.OpCode == OpCodes.Ldc_I4_S)
                return true; // often Vector3i(256, 16, ...) pattern continues

            // Terrain generators: y loops
            if (type.Name.IndexOf("Terrain", StringComparison.OrdinalIgnoreCase) >= 0
                && IsBranchCompare(next))
                return true;

            // ChunkBlockLayer vertical work
            if (type.Name.IndexOf("BlockLayer", StringComparison.OrdinalIgnoreCase) >= 0
                && IsBranchCompare(next))
                return true;

            // World / provider terrain
            if ((type.Name.StartsWith("ChunkProvider", StringComparison.Ordinal)
                 || type.Name == "World"
                 || type.Name == "WorldBlockFiller")
                && IsBranchCompare(next)
                && IsYBoundMethod(method))
                return true;

            return false;
        }

        static bool ShouldRewriteYMask255(
            TypeDefinition type,
            MethodDefinition method,
            Mono.Collections.Generic.Collection<Instruction> il,
            int index)
        {
            // Biome sentinel / texture packing / face paint — leave alone
            string m = method.Name;
            if (m.IndexOf("FaceTexture", StringComparison.OrdinalIgnoreCase) >= 0)
                return false;
            if (m.IndexOf("Texture", StringComparison.OrdinalIgnoreCase) >= 0
                && m.IndexOf("Height", StringComparison.OrdinalIgnoreCase) < 0)
                return false;
            if (m.IndexOf("Biome", StringComparison.OrdinalIgnoreCase) >= 0)
                return false;
            if (m == ".ctor" && type.Name == "Chunk")
            {
                // AreaMasterDominantBiome = 255 is a byte sentinel, not Y max
                var next = index + 1 < il.Count ? il[index + 1] : null;
                if (next != null && (next.OpCode == OpCodes.Stfld || next.OpCode == OpCodes.Stsfld))
                {
                    string f = next.Operand?.ToString() ?? "";
                    if (f.IndexOf("Biome", StringComparison.OrdinalIgnoreCase) >= 0)
                        return false;
                }
            }

            // Heightmap is still byte[] — SetHeight stores a byte, keep 255 clamp for that path
            if (m.Equals("SetHeight", StringComparison.Ordinal)
                || m.Equals("GetHeight", StringComparison.Ordinal)
                || m.Equals("GetMaxHeight", StringComparison.Ordinal)
                || m.Equals("SetTerrainHeight", StringComparison.Ordinal)
                || m.Equals("GetTerrainHeight", StringComparison.Ordinal))
                return false;

            var n = index + 1 < il.Count ? il[index + 1] : null;
            if (n == null) return false;

            // Y max compare / clamp in vertical methods
            if (IsYBoundMethod(method) && (IsBranchCompare(n) || n.OpCode == OpCodes.And
                || n.OpCode == OpCodes.Call || n.OpCode == OpCodes.Callvirt
                || n.OpCode == OpCodes.Cgt || n.OpCode == OpCodes.Clt
                || n.OpCode == OpCodes.Cgt_Un || n.OpCode == OpCodes.Clt_Un))
                return true;

            // cMaxHeight owner field stores
            if (type.Name.IndexOf("Terrain", StringComparison.OrdinalIgnoreCase) >= 0
                && (IsBranchCompare(n) || n.OpCode == OpCodes.Stfld))
                return true;

            if (type.Name == "ChunkProviderGenerateWorldFromRaw" && IsBranchCompare(n))
                return true;

            return false;
        }

        static bool IsYBoundMethod(MethodDefinition method)
        {
            if (YBoundMethodNames.Contains(method.Name))
                return true;
            string n = method.Name;
            if (n.IndexOf("Stability", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (n.IndexOf("Sunlight", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (n.IndexOf("Density", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (n.IndexOf("Terrain", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (n.IndexOf("SpawnPoint", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (n.IndexOf("Light", StringComparison.OrdinalIgnoreCase) >= 0
                && n.IndexOf("Slight", StringComparison.OrdinalIgnoreCase) < 0)
                return true;
            return false;
        }

        static bool IsBranchCompare(Instruction next)
        {
            return next.OpCode == OpCodes.Blt || next.OpCode == OpCodes.Blt_S
                || next.OpCode == OpCodes.Ble || next.OpCode == OpCodes.Ble_S
                || next.OpCode == OpCodes.Bgt || next.OpCode == OpCodes.Bgt_S
                || next.OpCode == OpCodes.Bge || next.OpCode == OpCodes.Bge_S
                || next.OpCode == OpCodes.Blt_Un || next.OpCode == OpCodes.Blt_Un_S
                || next.OpCode == OpCodes.Ble_Un || next.OpCode == OpCodes.Ble_Un_S
                || next.OpCode == OpCodes.Bgt_Un || next.OpCode == OpCodes.Bgt_Un_S
                || next.OpCode == OpCodes.Bge_Un || next.OpCode == OpCodes.Bge_Un_S
                || next.OpCode == OpCodes.Beq || next.OpCode == OpCodes.Beq_S
                || next.OpCode == OpCodes.Bne_Un || next.OpCode == OpCodes.Bne_Un_S;
        }

        /// <summary>
        /// XZ map: ldc.i4 256; newarr T; stfld mapField
        /// or BinaryReader.Read(..., 256) / Array.Clear(..., 256) / Alloc(256) for those maps.
        /// </summary>
        static bool IsXzMapSizeSite(Mono.Collections.Generic.Collection<Instruction> il, int index)
        {
            if (index + 1 >= il.Count) return false;
            var next = il[index + 1];

            if (next.OpCode == OpCodes.Newarr)
            {
                // Look ahead for stfld of XZ map
                for (int k = index + 2; k < Math.Min(index + 6, il.Count); k++)
                {
                    if (il[k].OpCode == OpCodes.Stfld || il[k].OpCode == OpCodes.Stsfld)
                    {
                        string f = il[k].Operand?.ToString() ?? "";
                        if (IsXzMapField(f)) return true;
                        // byte[] maps without matching name still often XZ in Chunk ctor
                        var tr = next.Operand as TypeReference;
                        if (tr != null && (tr.Name == "Byte" || tr.FullName == "System.Byte"
                            || tr.Name == "UInt16" || tr.Name.StartsWith("Enum", StringComparison.Ordinal)))
                        {
                            // newarr byte/ushort in Chunk is almost always XZ (heightmap etc.)
                            return true;
                        }
                    }
                }
                // newarr Byte without stfld yet — conservative: treat as XZ in Chunk
                var et = next.Operand as TypeReference;
                if (et != null && (et.Name == "Byte" || et.FullName == "System.Byte"))
                    return true;
            }

            // Read/Clear/Alloc length 256
            if (next.OpCode == OpCodes.Call || next.OpCode == OpCodes.Callvirt)
            {
                string mr = next.Operand?.ToString() ?? "";
                if (mr.IndexOf("Read(", StringComparison.Ordinal) >= 0) return true;
                if (mr.IndexOf("Clear", StringComparison.Ordinal) >= 0) return true;
                if (mr.IndexOf("Alloc", StringComparison.Ordinal) >= 0) return true;
            }

            return false;
        }

        /// <summary>
        /// Packing: idx % 256, idx / 256, y * 256 — XZ plane stride, must stay 256.
        /// </summary>
        static bool IsXzPlaneStrideSite(Mono.Collections.Generic.Collection<Instruction> il, int index)
        {
            if (index + 1 >= il.Count) return false;
            var next = il[index + 1];
            if (next.OpCode == OpCodes.Rem || next.OpCode == OpCodes.Rem_Un)
                return true;
            if (next.OpCode == OpCodes.Div || next.OpCode == OpCodes.Div_Un)
                return true;
            // y * 256 for linear index within chunk (XZ area stride)
            if (next.OpCode == OpCodes.Mul)
            {
                // AABB world size uses mul too — CalculateAABB needs YDim not XZ.
                // Disambiguate: if followed by add of x/z style, packing; if conv.r4 world AABB, Y.
                for (int k = index + 2; k < Math.Min(index + 5, il.Count); k++)
                {
                    if (il[k].OpCode == OpCodes.Conv_R4)
                        return false; // world AABB — allow Y rewrite via other rules
                }
                return true; // default: packing stride
            }
            // shl with 8 is packing; we don't rewrite 8. For 256, no shl.
            return false;
        }

        static bool IsXzMapField(string fieldRef)
        {
            foreach (var s in XzMapFieldSnippets)
            {
                if (fieldRef.IndexOf(s, StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }
            return false;
        }

        static int? ReadLdcI4(Instruction ins)
        {
            if (ins.OpCode == OpCodes.Ldc_I4)
                return (int)ins.Operand;
            if (ins.OpCode == OpCodes.Ldc_I4_S)
                return (sbyte)ins.Operand;
            if (ins.OpCode == OpCodes.Ldc_I4_0) return 0;
            if (ins.OpCode == OpCodes.Ldc_I4_1) return 1;
            if (ins.OpCode == OpCodes.Ldc_I4_2) return 2;
            if (ins.OpCode == OpCodes.Ldc_I4_3) return 3;
            if (ins.OpCode == OpCodes.Ldc_I4_4) return 4;
            if (ins.OpCode == OpCodes.Ldc_I4_5) return 5;
            if (ins.OpCode == OpCodes.Ldc_I4_6) return 6;
            if (ins.OpCode == OpCodes.Ldc_I4_7) return 7;
            if (ins.OpCode == OpCodes.Ldc_I4_8) return 8;
            if (ins.OpCode == OpCodes.Ldc_I4_M1) return -1;
            return null;
        }

        static void WriteLdcI4(Instruction ins, int value)
        {
            ins.OpCode = OpCodes.Ldc_I4;
            ins.Operand = value;
        }
    }
}
