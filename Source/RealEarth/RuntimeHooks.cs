using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
namespace RealEarth
{
    /// <summary>
    /// Reflection-based Harmony wiring for one continuous map session.
    /// Does not hard-compile against a specific Assembly-CSharp build.
    ///
    /// Streamed inject path:
    ///   1) GetTerrainHeightByteAt / GetTerrainHeightAt → RealEarth sample (height source)
    ///   2) GenerateTerrain(World, Chunk, ...) postfix → rewrite density from FillChunkHeights
    ///   3) Player tick → absolute stream + origin slide
    /// </summary>
    public static class RuntimeHooks
    {
        static bool _applied;
        static bool _harmonyMissing;
        static object? _harmony;
        static int _retryBudget = 8;
        /// <summary>
        /// MethodBases already Harmony-patched. PatchPostfix is idempotent: never stack postfixes.
        /// Survives retry when GenerateTerrainPatches==0 but ChunkIndexPatches&gt;0.
        /// </summary>
        static readonly HashSet<MethodBase> _patchedMethods = new HashSet<MethodBase>();

        /// <summary>
        /// Applied means something useful bound. Recomputed from actual stats after
        /// every patch attempt so a failed bind never latches a stale true.
        /// </summary>
        static bool HasUsefulBinding
            => InjectPatchStats.HasMinimalInjectBinding
                || InjectPatchStats.PlayerTickPatches > 0
                || InjectPatchStats.WorldReadyPatches > 0;

        public static void Apply()
        {
            if (_applied) return;

            try
            {
                var harmonyType = EngineReflection.FindType("HarmonyLib.Harmony", "0Harmony");
                if (harmonyType == null)
                {
                    // Do not set _applied: WorldReady / player tick may retry when assemblies load.
                    _harmonyMissing = true;
                    ChunkTerrainInject.InjectBlocked = true;
                    ModApi.Log(
                        "RuntimeHooks: Harmony not loaded (keep Mods/0_TFP_Harmony). " +
                        "Inject BLOCKED (fail-closed); will retry on world ready.");
                    return;
                }

                _harmonyMissing = false;
                if (_harmony == null)
                    _harmony = Activator.CreateInstance(harmonyType, "com.realearth.7dtd.singleworld");

                // Do not Reset patch MethodBase set or re-count from zero on re-entry.
                if (_patchedMethods.Count == 0)
                {
                    InjectPatchStats.Reset();
                    TileSamplePolicy.ResetCounters();
                }
                int n = 0;
                int pt = TryPatchPlayerTick();
                InjectPatchStats.AddPlayerTick(pt);
                n += pt > 0 ? 1 : 0;
                int wr = TryPatchWorldSpawn();
                InjectPatchStats.AddWorldReady(wr);
                n += wr > 0 ? 1 : 0;
                int hq = TryPatchTerrainHeightQueries();
                n += hq;
                int gen = TryPatchChunkTerrainGenerate();
                n += gen > 0 ? 1 : 0;
                // Only mark applied when something useful bound; else leave false so Apply can re-run.
                _applied = HasUsefulBinding;
                EnforceInjectGate();
                ModApi.Log(
                    $"RuntimeHooks: {n} patch group(s). MapMode={ModApi.Config.MapMode} " +
                    $"FailClosedMissingTiles={ModApi.Config?.FailClosedMissingTiles} " +
                    $"inject={InjectPatchStats.FormatSummary()}");
            }
            catch (Exception ex)
            {
                ModApi.Log($"RuntimeHooks failed: {ex.Message}");
                // Recompute gate from actual binds (do not leave InjectBlocked stuck true with healthy patches).
                _applied = HasUsefulBinding;
                EnforceInjectGate();
            }
        }

        /// <summary>
        /// Re-run patch discovery when Assembly-CSharp / Harmony appear after first InitMod.
        /// Safe to call from WorldReady / player tick. Never full re-Apply after a successful
        /// Harmony instance exists (would stack postfixes).
        /// PatchPostfix is idempotent via _patchedMethods; gen retries even when index already bound.
        /// </summary>
        public static void TryRetryApply()
        {
            if (_applied && InjectPatchStats.HasProductInjectBinding)
            {
                EnforceInjectGate(); // clear InjectBlocked if catch path left it stuck
                return;
            }
            if (_retryBudget <= 0)
            {
                EnforceInjectGate();
                return;
            }
            _retryBudget--;

            // First time Harmony appears: full Apply once only.
            if (_harmony == null || _harmonyMissing)
            {
                Apply();
                return;
            }

            // Harmony already live: only discover missing binds.
            // PatchPostfix is idempotent via _patchedMethods (safe to re-scan gen even if
            // ChunkIndexPatches>0; otherwise expanded product never gets GenerateTerrain).
            try
            {
                if (InjectPatchStats.HeightQueryPatches == 0)
                    TryPatchTerrainHeightQueries();
                if (InjectPatchStats.GenerateTerrainPatches == 0)
                {
                    int gen = TryPatchChunkTerrainGenerate();
                    if (gen > 0)
                        ModApi.Log("RuntimeHooks retry: GenerateTerrain binds added.");
                }
                if (InjectPatchStats.PlayerTickPatches == 0)
                    InjectPatchStats.AddPlayerTick(TryPatchPlayerTick());
                if (InjectPatchStats.WorldReadyPatches == 0)
                    InjectPatchStats.AddWorldReady(TryPatchWorldSpawn());
                _applied = HasUsefulBinding;
            }
            catch (Exception ex)
            {
                ModApi.Log("RuntimeHooks retry: " + ex.Message);
            }
            EnforceInjectGate();
        }

        static MethodInfo? FindMethod(Type type, string name)
        {
            return type.GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
                .Where(m => m.Name == name)
                .OrderByDescending(m => m.GetParameters().Length)
                .FirstOrDefault();
        }

        static Assembly? GameAssembly()
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (string.Equals(asm.GetName().Name, "Assembly-CSharp", StringComparison.OrdinalIgnoreCase))
                    return asm;
            }
            return null;
        }

        static IEnumerable<Type> TerrainRelatedTypes(Assembly game)
        {
            // Concrete preferred first (RWG host = TerrainGeneratorWithBiomeResource)
            return EngineReflection.SafeGetTypes(game)
                .Where(t => t != null && HeightQueryPatcher.IsTerrainRelatedTypeName(t.Name))
                .OrderByDescending(HeightQueryPatcher.TypePatchPriority)
                .Cast<Type>();
        }

        /// <summary>
        /// Patch EntityPlayer (dedicated + remote MP) AND EntityPlayerLocal (solo/host client).
        /// Must not return after the first success: that left dedicated with only Local patched
        /// and remote players never registered stream foci.
        /// </summary>
        static int TryPatchPlayerTick()
        {
            // Count only Update-path binds (not unload). Unload success must not mask missing tick.
            int tickPatched = 0;
            var seen = new HashSet<MethodBase>();
            // EntityPlayer first: covers remote + local when Update is not overridden.
            // EntityPlayerLocal second: any client-only override still gets a focus tick.
            foreach (var tn in new[] { "EntityPlayer", "EntityPlayerLocal" })
            {
                var t = EngineReflection.FindType(tn);
                if (t == null) continue;
                bool typeDone = false;
                foreach (var mn in new[] { "Update", "OnUpdatePosition", "MoveEntityHeaded" })
                {
                    if (typeDone) break;
                    var m = FindMethod(t, mn);
                    if (m == null) continue;
                    // Same MethodBase when Local inherits base Update, so patch once only.
                    if (!seen.Add(m)) continue;
                    if (PatchPostfix(m, typeof(HooksImpl).GetMethod(nameof(HooksImpl.PlayerTickPostfix))!))
                    {
                        ModApi.Log($"Patched player: {t.Name}.{m.Name} (decl={m.DeclaringType?.Name})");
                        tickPatched++;
                        typeDone = true;
                    }
                }
            }
            // Best-effort: remove stream focus when a player entity is destroyed/unloaded.
            int unloadPatched = 0;
            foreach (var tn in new[] { "EntityPlayer", "EntityAlive" })
            {
                var t = EngineReflection.FindType(tn);
                if (t == null) continue;
                foreach (var mn in new[] { "OnEntityUnload", "Despawn", "Kill" })
                {
                    var m = FindMethod(t, mn);
                    if (m == null) continue;
                    if (!seen.Add(m)) continue;
                    if (PatchPostfix(m, typeof(HooksImpl).GetMethod(nameof(HooksImpl.PlayerUnloadPostfix))!))
                    {
                        ModApi.Log($"Patched player unload: {t.Name}.{m.Name}");
                        unloadPatched++;
                        break;
                    }
                }
            }
            if (tickPatched == 0)
                ModApi.Log(
                    $"Player tick patch not bound yet (unloadBound={unloadPatched > 0}). " +
                    "Stream tick still works on world load.");
            else
                ModApi.Log(
                    $"Player tick patches bound: {tickPatched} " +
                    $"(EntityPlayer + EntityPlayerLocal when present; unload={unloadPatched})");
            return tickPatched;
        }

        static int TryPatchWorldSpawn()
        {
            int n = 0;
            var t = EngineReflection.FindType("GameManager");
            if (t != null)
            {
                foreach (var mn in new[] { "StartGame", "WorldLoaded", "RequestToSpawnPlayer" })
                {
                    var m = FindMethod(t, mn);
                    if (m == null) continue;
                    if (PatchPostfix(m, typeof(HooksImpl).GetMethod(nameof(HooksImpl.WorldReadyPostfix))!))
                    {
                        ModApi.Log($"Patched world: {t.Name}.{m.Name}");
                        n++;
                        break;
                    }
                }
                // Persist session into stock save on SaveWorld.
                foreach (var mn in new[] { "SaveWorld", "SaveAndCleanupWorld" })
                {
                    var m = FindMethod(t, mn);
                    if (m == null) continue;
                    if (PatchPostfix(m, typeof(HooksImpl).GetMethod(nameof(HooksImpl.WorldSavePostfix))!))
                    {
                        ModApi.Log($"Patched world save: {t.Name}.{m.Name}");
                        n++;
                        break;
                    }
                }
            }
            // World.SaveWorldState also writes to GetSaveGameDir, so hook as secondary.
            var wt = EngineReflection.FindType("World");
            if (wt != null)
            {
                var m = FindMethod(wt, "SaveWorldState");
                if (m != null
                    && PatchPostfix(m, typeof(HooksImpl).GetMethod(nameof(HooksImpl.WorldSavePostfix))!))
                {
                    ModApi.Log("Patched World.SaveWorldState for RealEarth session persist");
                    n++;
                }
            }
            return n > 0 ? 1 : 0;
        }

        /// <summary>
        /// Primary Streamed inject: override EVERY concrete GetTerrainHeight* so RWG host
        /// (TerrainGeneratorWithBiomeResource) and FromRaw/DTM all sample RealEarth Y.
        /// No patch-count cap: 3.0.1 has 8+ height methods across generators.
        /// </summary>
        static int TryPatchTerrainHeightQueries()
        {
            var game = GameAssembly();
            if (game == null)
            {
                ModApi.Log("Assembly-CSharp not loaded; height-query patches deferred.");
                return 0;
            }

            var methods = HeightQueryPatcher.DiscoverHeightQueryMethods(game);
            int patched = 0;
            int failed = 0;
            var seen = new HashSet<string>();

            foreach (var m in methods)
            {
                string key = HeightQueryPatcher.FormatMethod(m);
                if (!seen.Add(key))
                    continue;

                MethodInfo? postfix = SelectHeightPostfix(m);
                if (postfix == null)
                {
                    failed++;
                    continue;
                }

                if (PatchPostfix(m, postfix))
                {
                    ModApi.Log($"Patched height query: {key}");
                    patched++;
                }
                else
                {
                    failed++;
                }
            }

            InjectPatchStats.AddHeightQuery(patched);
            ModApi.Log(
                $"Height-query inject: patched={patched} failed={failed} discovered={methods.Count} " +
                $"(concrete first; includes TerrainGeneratorWithBiomeResource when present)");
            if (patched == 0)
                ModApi.Log("Height-query inject not bound for this build (will try GenerateTerrain rewrite).");
            return patched > 0 ? 1 : 0;
        }

        static MethodInfo? SelectHeightPostfix(MethodInfo m)
        {
            var ps = m.GetParameters();
            bool floatArgs = ps.Length >= 2 && (ps[0].ParameterType == typeof(float) || ps[0].ParameterType == typeof(double));

            if (m.ReturnType == typeof(byte))
                return typeof(HooksImpl).GetMethod(nameof(HooksImpl.HeightBytePostfix))!;
            if (m.ReturnType == typeof(int))
                return typeof(HooksImpl).GetMethod(nameof(HooksImpl.HeightIntPostfix))!;
            if (m.ReturnType == typeof(float) || m.ReturnType == typeof(double))
            {
                if (floatArgs)
                    return typeof(HooksImpl).GetMethod(nameof(HooksImpl.HeightFloatFromFloatArgsPostfix))!;
                return typeof(HooksImpl).GetMethod(nameof(HooksImpl.HeightFloatPostfix))!;
            }
            return null;
        }

        /// <summary>
        /// Secondary inject: after GenerateTerrain, rewrite blocks+density from samples.
        /// Patches all matching generators (no cap), concrete first.
        /// </summary>
        static int TryPatchChunkTerrainGenerate()
        {
            var game = GameAssembly();
            if (game == null)
                return 0;

            int genPatched = 0;
            int idxPatched = 0;
            var seen = new HashSet<string>();
            foreach (var t in TerrainRelatedTypes(game))
            {
                MethodInfo[] methods;
                try
                {
                    methods = t.GetMethods(
                        BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
                }
                catch
                {
                    continue;
                }

                // Interfaces cannot be Harmony-patched (TargetInvocationException).
                // Abstract *classes* with method bodies (e.g. TerrainGeneratorWithBiomeResource)
                // still need postfix inject.
                if (t.IsInterface)
                    continue;

                foreach (var m in methods)
                {
                    var ps = m.GetParameters();

                    // GenerateTerrain(World, Chunk, GameRandom, ...)
                    if (m.Name.Equals("GenerateTerrain", StringComparison.OrdinalIgnoreCase)
                        || m.Name.Equals("generateTerrain", StringComparison.OrdinalIgnoreCase))
                    {
                        if (ps.Length >= 2
                            && ps[1].ParameterType.Name.IndexOf("Chunk", StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            string key = $"{t.Name}.{m.Name}/{ps.Length}";
                            if (!seen.Add(key)) continue;
                            if (PatchPostfix(m, typeof(HooksImpl).GetMethod(nameof(HooksImpl.GenerateTerrainPostfix))!))
                            {
                                ModApi.Log($"Patched terrain gen: {t.Name}.{m.Name}");
                                genPatched++;
                            }
                        }
                    }
                }
            }

            // Chunk-index hooks (stream tiles), skip interfaces only
            foreach (var t in TerrainRelatedTypes(game))
            {
                if (t.IsInterface)
                    continue;
                MethodInfo[] methods;
                try
                {
                    methods = t.GetMethods(
                        BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
                }
                catch
                {
                    continue;
                }
                foreach (var m in methods)
                {
                    var ps = m.GetParameters();
                    if ((m.Name.IndexOf("Generate", StringComparison.OrdinalIgnoreCase) >= 0
                         || m.Name.IndexOf("Fill", StringComparison.OrdinalIgnoreCase) >= 0)
                        && ps.Length >= 2
                        && ps[0].ParameterType == typeof(int)
                        && ps[1].ParameterType == typeof(int)
                        && m.Name.IndexOf("GenerateTerrain", StringComparison.OrdinalIgnoreCase) < 0)
                    {
                        string key = $"{t.Name}.{m.Name}/idx";
                        if (!seen.Add(key)) continue;
                        if (PatchPostfix(m, typeof(HooksImpl).GetMethod(nameof(HooksImpl.ChunkIndexPostfix))!))
                        {
                            ModApi.Log($"Patched terrain index: {t.Name}.{m.Name}");
                            idxPatched++;
                        }
                    }
                }
            }

            InjectPatchStats.AddGenerateTerrain(genPatched);
            InjectPatchStats.AddChunkIndex(idxPatched);
            int patched = genPatched + idxPatched;
            if (patched == 0)
            {
                ModApi.Log(
                    "Terrain inject not bound for this build. " +
                    "Use MapMode=Baked + realearth bake-world for full terrain on one map, " +
                    "or retarget Harmony after inspecting Assembly-CSharp.");
            }
            else
            {
                ModApi.Log($"Terrain gen/index inject: gen={genPatched} index={idxPatched}");
            }
            return patched > 0 ? 1 : 0;
        }

        /// <summary>
        /// Streamed product path: hard-gate when no height/gen inject bound (stock RWG under RealEarth skin).
        /// </summary>
        public static void EnforceInjectGate()
        {
            var cfg = ModApi.Config;
            if (cfg == null) return;
            bool streamed = !string.Equals(cfg.MapMode, "Baked", StringComparison.OrdinalIgnoreCase);
            if (!streamed)
            {
                ChunkTerrainInject.InjectBlocked = false;
                return;
            }
            // Product Streamed: require gen rewrite when expanded; height-only is not enough for tall solid.
            if (InjectPatchStats.HasProductInjectBinding)
            {
                ChunkTerrainInject.InjectBlocked = false;
                return;
            }
            ChunkTerrainInject.InjectBlocked = true;
            if (InjectPatchStats.HasMinimalInjectBinding)
            {
                ModApi.Log(
                    "INJECT GATE: Streamed+expanded needs GenerateTerrain bind for solid columns " +
                    $"(heightQ={InjectPatchStats.HeightQueryPatches} gen={InjectPatchStats.GenerateTerrainPatches}). " +
                    "Height inject DISABLED until gen rewrite binds (reinject / retry).");
            }
            else
            {
                ModApi.Log(
                    "INJECT GATE: Streamed mode has no height/GenerateTerrain Harmony binds. " +
                    "Height inject DISABLED to avoid silent stock RWG under RealEarth. " +
                    "Check 0_TFP_Harmony + Assembly-CSharp method names (reinject).");
            }
        }

        /// <summary>
        /// Idempotent Harmony postfix: each MethodBase is patched at most once per process.
        /// Retries / second Apply path must call this rather than raw Harmony.Patch.
        /// </summary>
        static bool PatchPostfix(MethodBase target, MethodInfo postfix)
        {
            try
            {
                if (_harmony == null || target == null) return false;
                // Global already-patched set: prevents stacked postfixes on retry.
                if (!_patchedMethods.Add(target))
                    return false;

                var harmonyMethodType = EngineReflection.FindType("HarmonyLib.HarmonyMethod", "0Harmony");
                var harmonyType = _harmony.GetType();
                if (harmonyMethodType == null)
                {
                    _patchedMethods.Remove(target);
                    return false;
                }

                var postfixHm = Activator.CreateInstance(harmonyMethodType, postfix);

                MethodInfo? patch = null;
                foreach (var m in harmonyType.GetMethods(BindingFlags.Instance | BindingFlags.Public))
                {
                    if (m.Name != "Patch") continue;
                    var p = m.GetParameters();
                    if (p.Length >= 3 && p[0].ParameterType == typeof(MethodBase))
                    {
                        patch = m;
                        break;
                    }
                }
                if (patch == null)
                {
                    _patchedMethods.Remove(target);
                    return false;
                }

                var ps = patch.GetParameters();
                var args = new object?[ps.Length];
                args[0] = target;
                for (int i = 1; i < ps.Length; i++)
                {
                    var n = (ps[i].Name ?? "").ToLowerInvariant();
                    if (n.Contains("postfix"))
                        args[i] = postfixHm;
                    else if (i == 2 && !n.Contains("prefix"))
                        args[i] = postfixHm;
                    else
                        args[i] = null;
                }
                if (ps.Length >= 3 && args[2] == null)
                    args[2] = postfixHm;

                patch.Invoke(_harmony, args);
                return true;
            }
            catch (Exception ex)
            {
                // Roll back reservation so a later retry can try again after type load settles.
                _patchedMethods.Remove(target);
                // Interfaces/abstracts expected to fail, so keep log quiet unless concrete.
                var dt = target.DeclaringType;
                if (dt != null && !dt.IsInterface && !dt.IsAbstract)
                    ModApi.Log($"Patch failed {dt.Name}.{target.Name}: {ex.Message}");
                return false;
            }
        }
    }

    public static class HooksImpl
    {
        // Log budgets are cross-thread: _injectErrLogBudget is consumed by the
        // chunk-generation thread (GenerateTerrain/ChunkIndex postfixes) while
        // WorldReadyPostfix resets it on the main thread; plain RMW would race.
        static int _peakLogBudget = 3;
        /// <summary>Budget for tick-path errors so persistent failures stay visible without spam.</summary>
        static int _tickErrLogBudget = 8;
        /// <summary>Budget for inject-path errors: a swallowed gen/inject exception otherwise
        /// looks like "terrain is stock RWG under RealEarth" with zero trace.</summary>
        static int _injectErrLogBudget = 8;
        /// <summary>Hoisted: TryGetEntityId runs every frame per player (no per-call alloc).</summary>
        static readonly string[] EntityIdMemberNames = { "entityId", "EntityId", "EntityID" };

        /// <summary>
        /// Consume one budget slot atomically (gen thread + main thread share them).
        /// </summary>
        static bool ConsumeBudget(ref int budget) => Interlocked.Decrement(ref budget) >= 0;

        static void ResetBudget(ref int budget, int value)
            => Interlocked.Exchange(ref budget, value);

        public static void PlayerTickPostfix(object __instance)
        {
            try
            {
                RuntimeHooks.TryRetryApply();

                // Read player block pos once: FOW debug, city discovery, and the stream
                // tick all need it (a second TryGetPos here doubled per-frame reflection
                // boxing for every player).
                bool hasPos = EngineReflection.TryGetPos(__instance, out int x, out int y, out int z);

                // FOW debug + city discover-on-approach need player block pos
                if (hasPos)
                {
                    MapReveal.TryRevealIfConfigured(x, z);
                    CityMapLabels.TickPlayer(x, z);
                }
                else
                    MapReveal.TryRevealIfConfigured();

                if (ModApi.Session == null || !ModApi.Session.IsStreamed)
                    return;

                if (!hasPos)
                    return;

                // Stable focus id: real entityId only (no identity-hash merge of MP bubbles).
                int focusId = TryGetEntityId(__instance);
                bool isPrimary = IsLocalPlayerEntity(__instance);
                // Dedicated solo: no EntityPlayerLocal; still must advance session absolute when count≤1.
                bool updateAbs = WorldSession.ShouldUpdateSessionAbsolute(isPrimary);
                // Without entityId, remotes must not all stomp focus 0; only primary/solo uses 0.
                if (focusId == 0 && !isPrimary && !updateAbs)
                {
                    RuntimePoiInject.TickPlayer(x, z);
                    return;
                }
                if (ModApi.Session.TickPlayerLocal(
                        x, z, out int nx, out int nz,
                        out int dOx, out int dOz, focusId, updateSessionAbsolute: updateAbs))
                {
                    // Origin already moved; if we cannot reposition the sliding player, roll origin back.
                    if (!EngineReflection.TrySetPos(__instance, nx, y, nz))
                    {
                        if (dOx != 0 || dOz != 0)
                        {
                            ModApi.Session.SetOrigin(
                                ModApi.Session.OriginEarthX - dOx,
                                ModApi.Session.OriginEarthZ - dOz);
                            ModApi.Log(
                                $"Origin slide rolled back (SetPos failed) dOrigin=({dOx},{dOz})");
                        }
                        return;
                    }
                    // Players, vehicles, claims: keep absolute Earth after origin slide.
                    if (dOx != 0 || dOz != 0)
                    {
                        OriginSlideRemap.RemapAll(__instance, dOx, dOz);
                        RuntimePoiInject.OnOriginSlide();
                        // Drop tile cache so post-slide sampling is not stale; chunks still need regen.
                        ModApi.Streamer?.InvalidateHotCache();
                        ModApi.Streamer?.EnsureHotAround(
                            ModApi.Session.AbsoluteX, ModApi.Session.AbsoluteZ,
                            radius: Math.Max(1, ModApi.Config?.StreamRadiusTiles ?? 2),
                            allowSyncLoad: true);
                        // Close SoloSlide mesh/voxel desync: rewrite already-loaded chunk
                        // columns under the new origin instead of waiting for regen.
                        try
                        {
                            ChunkTerrainInject.ReinjectLoadedChunksAround(
                                ReflectCache.GetEngineWorld(), nx, nz);
                        }
                        catch (Exception ex)
                        {
                            // Never break the slide path, but a failed reinject leaves loaded
                            // chunks desynced (the exact symptom this call exists to close);
                            // log so "world looks torn after slide" stays debuggable.
                            if (ConsumeBudget(ref _tickErrLogBudget))
                            {
                                ModApi.Log(
                                    $"Origin slide reinject error: {ex.GetType().Name}: {ex.Message}");
                            }
                        }
                    }
                    ModApi.Log(
                        $"Single-map origin slide → local ({nx},{nz}) focus={focusId} " +
                        $"dOrigin=({dOx},{dOz})");
                    CityMapLabels.RefreshAfterOriginSlide();
                    CityMapLabels.TickPlayer(nx, nz);
                    RuntimePoiInject.TickPlayer(nx, nz);
                    try
                    {
                        SessionStateStore.TrySave(ModApi.Session, ModApi.Config);
                    }
                    catch { /* ignore */ }
                }
                else
                {
                    RuntimePoiInject.TickPlayer(x, z);
                }
                if (ChunkTerrainInject.SessionInjectCount > 0 && ConsumeBudget(ref _peakLogBudget))
                {
                    ModApi.Log(
                        $"Height inject stats: count={ChunkTerrainInject.SessionInjectCount} " +
                        $"blocksOk={ChunkTerrainInject.SessionBlocksApplied} " +
                        $"sessionPeak={ChunkTerrainInject.SessionPeakHeight} " +
                        $"hotTiles={ModApi.Streamer?.HotTileCount ?? 0} " +
                        $"foci={ModApi.Streamer?.FocusCount ?? 0}");
                }
            }
            catch (Exception ex)
            {
                // Never break the gameplay loop, but do not fail silently either:
                // a stuck tick path otherwise looks like "tiles never stream" with zero trace.
                if (ConsumeBudget(ref _tickErrLogBudget))
                {
                    ModApi.Log($"PlayerTick postfix error: {ex.GetType().Name}: {ex.Message}");
                }
            }
        }

        /// <summary>
        /// entityId when present. Returns 0 if unknown (single primary focus; no identity-hash collisions).
        /// Per-frame path: member lookups memoized in ReflectCache.
        /// </summary>
        static int TryGetEntityId(object entity)
        {
            try
            {
                var t = entity.GetType();
                foreach (var name in EntityIdMemberNames)
                {
                    if (ReflectCache.TryReadIntMember(entity, name, out int v))
                        return v;
                }
            }
            catch
            {
                // fall through
            }
            return 0;
        }

        static bool IsLocalPlayerEntity(object entity)
        {
            try
            {
                string n = entity.GetType().Name;
                if (n.IndexOf("Local", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
                // Dedicated host: primary player when only one, or isEntityRemote == false
                var t = entity.GetType();
                var remote = ReflectCache.PropPub(t, "isEntityRemote") ?? ReflectCache.PropPub(t, "IsEntityRemote");
                if (remote != null && remote.PropertyType == typeof(bool))
                    return !(bool)(remote.GetValue(entity) ?? true);
            }
            catch { /* ignore */ }
            return false;
        }

        /// <summary>Drop stream focus when a player entity unloads (MP disconnect / despawn).</summary>
        public static void PlayerUnloadPostfix(object __instance)
        {
            try
            {
                if (__instance == null) return;
                // Only care about player-like types
                string n = __instance.GetType().Name;
                if (n.IndexOf("Player", StringComparison.OrdinalIgnoreCase) < 0)
                    return;
                int focusId = TryGetEntityId(__instance);
                // Never RemoveFocus(0) for unknown id (would wipe primary / entire hot set).
                if (focusId == 0 && !IsLocalPlayerEntity(__instance))
                    return;
                ModApi.Streamer?.RemoveFocus(focusId);
            }
            catch
            {
                // never break unload path
            }
        }

        public static void WorldReadyPostfix(object? __instance)
        {
            try
            {
                ModApi.Log("Single-map world ready.");
                RuntimeHooks.TryRetryApply();
                RuntimeHooks.EnforceInjectGate();
                var cfg = ModApi.Config;
                var session = ModApi.Session;
                if (session == null || cfg == null)
                    return;

                // Prefer durable session restore; else config spawn lon/lat.
                // Both paths prefetch the spawn area hot (restore inline, spawn via
                // SpawnAtLonLat); player tick registers real entity focus ids later.
                // Fresh world in a long-lived process: drop hot tiles / miss deadlines
                // (and resolved surface elevations) from any previous world first;
                // unload postfixes are best-effort, so old foci could otherwise keep
                // their bubbles pinned until FocusStaleMs and the store would resample
                // from them. Spawn prefetch below reloads synchronously.
                ModApi.Streamer?.InvalidateHotCache();
                EngineHeight.EngineHeightMod.Store.Clear();
                bool restored = SessionStateStore.TryLoad(session);
                if (restored)
                {
                    ModApi.Log(
                        $"Session restored absolute=({session.AbsoluteX},{session.AbsoluteZ}) " +
                        $"origin=({session.OriginEarthX},{session.OriginEarthZ})");
                    ModApi.Streamer?.EnsureHotAround(
                        session.AbsoluteX, session.AbsoluteZ,
                        radius: Math.Max(1, cfg.StreamRadiusTiles), allowSyncLoad: true);
                }
                else
                {
                    cfg.ResolveSpawnLonLat(out double lon, out double lat);
                    session.SpawnAtLonLat(lon, lat);
                }

                // Pack-center diagnostic: EnsureHotAround only (never register focus 0).
                if (cfg.WorldWidth > 0 && cfg.WorldHeight > 0)
                {
                    int mid = Math.Max(0, cfg.WorldWidth / 2);
                    int midZ = Math.Max(0, cfg.WorldHeight / 2);
                    ModApi.Streamer?.EnsureHotAround(mid, midZ, radius: 1, allowSyncLoad: true);
                    int h = 0;
                    if (ModApi.Streamer != null
                        && ModApi.Streamer.TrySample(mid, midZ, out float elevM, out _, out _))
                    {
                        if (EngineHeight.EngineHeightMod.Policy != null)
                            h = EngineHeight.EngineHeightMod.Policy.MapMetersToGameY(elevM);
                        else
                            h = HeightInjectMath.MetersToGameYOneToOne(
                                elevM, cfg.SeaLevelGameY, cfg.EngineMaxGameY);
                    }
                    ModApi.Log(
                        $"Spawn sample pack-center earth=({mid},{midZ}) gameY={h} " +
                        $"(expect ~500 staged / ~8949 Everest DEM; focus not stomped)");
                }

                MapReveal.Reset();
                MapReveal.TryRevealIfConfigured();
                CityMapLabels.Reset();
                RuntimePoiInject.Reset();
                ChunkTerrainInject.ResetSessionCounters();
                ResetBudget(ref _tickErrLogBudget, 8);
                ResetBudget(ref _injectErrLogBudget, 8);
                try
                {
                    var snap = SessionStateStore.Capture(session, cfg);
                    ModApi.Log(
                        "Session snapshot: " + snap.ToJson() +
                        " path=" + WorldSavePath.SessionPath());
                    SessionStateStore.TrySave(session, cfg);
                }
                catch (Exception sex)
                {
                    ModApi.Log("Session snapshot skip: " + sex.Message);
                }

                ModApi.Log(
                    $"FullSolidBlockFillMax={ChunkTerrainInject.EffectiveFullDualFillMaxSurface()} " +
                    $"(config={cfg.FullSolidBlockFillMaxSurface}, expanded={EngineHeight.EngineHeightMod.EngineExpanded}) " +
                    $"runtimePoi={cfg.EnableRuntimePoiInject}");

                if (EngineHeight.EngineHeightMod.ProductHeightBlocked)
                {
                    ModApi.Log(
                        "PRODUCT HEIGHT CAPPED: YDim expand required for true real-height columns. " +
                        $"Heights clamp to allocY={EngineHeight.EngineHeightMod.AllocatableColumnMaxY} " +
                        "(inject still samples RealEarth, not stock RWG). " +
                        "Run make engine-expand or set EngineHeightStockSafe=true.");
                }
            }
            catch (Exception ex)
            {
                ModApi.Log($"WorldReady: {ex.Message}");
            }
        }

        /// <summary>After stock world save: write realearth.session.json into save dir + mod Config.</summary>
        public static void WorldSavePostfix(object? __instance)
        {
            try
            {
                if (ModApi.Session == null) return;
                SessionStateStore.TrySave(ModApi.Session, ModApi.Config);
            }
            catch
            {
                // never break save path
            }
        }

        /// <summary>Harmony postfix: override byte terrain height with Streamed sample.</summary>
        public static void HeightBytePostfix(int __0, int __1, ref byte __result)
        {
            try
            {
                if (ChunkTerrainInject.TryOverrideHeightByte(__0, __1, out byte h))
                    __result = h;
            }
            catch
            {
                // ignore
            }
        }

        public static void HeightFloatPostfix(int __0, int __1, ref float __result)
        {
            try
            {
                // Full 1:1 game Y as float (can be 8949) for APIs that do not use byte heightmaps
                if (ChunkTerrainInject.TryOverrideHeightInt(__0, __1, out int h))
                    __result = h;
            }
            catch
            {
                // ignore
            }
        }

        /// <summary>World.GetHeightAt(float,float) and similar: full 1:1 meters/blocks.</summary>
        public static void HeightFloatFromFloatArgsPostfix(float __0, float __1, ref float __result)
        {
            try
            {
                // Floor (not truncate): negative local XZ are normal after origin fold/slide.
                int bx = (int)Math.Floor(__0);
                int bz = (int)Math.Floor(__1);
                if (ChunkTerrainInject.TryOverrideHeightInt(bx, bz, out int h))
                    __result = h;
            }
            catch
            {
                // ignore
            }
        }

        public static void HeightIntPostfix(int __0, int __1, ref int __result)
        {
            try
            {
                // Full int height (up to 11000) when engine-height mod is active
                if (ChunkTerrainInject.TryOverrideHeightInt(__0, __1, out int h))
                    __result = h;
            }
            catch
            {
                // ignore
            }
        }

        /// <summary>After GenerateTerrain(World, Chunk, ...): inject densities from samples.</summary>
        public static void GenerateTerrainPostfix(object? __instance, object? __0, object? __1)
        {
            try
            {
                if (ModApi.Session == null || !ModApi.Session.IsStreamed)
                    return;

                // Prefer Chunk as second arg
                object? chunk = null;
                int cx = 0, cz = 0;
                if (__1 != null && __1.GetType().Name.IndexOf("Chunk", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    chunk = __1;
                    if (!TryGetChunkIndices(chunk, out cx, out cz))
                        return;
                }
                else if (__0 != null && __0.GetType().Name.IndexOf("Chunk", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    chunk = __0;
                    if (!TryGetChunkIndices(chunk, out cx, out cz))
                        return;
                }
                else
                    return;

                ChunkTerrainInject.OnChunkGenerated(__instance, cx, cz, chunk);
            }
            catch (Exception ex)
            {
                // Never break chunk gen, but do not fail silently: an aborted density
                // rewrite leaves stock RWG terrain that looks like a streaming bug.
                if (ConsumeBudget(ref _injectErrLogBudget))
                {
                    ModApi.Log(
                        $"GenerateTerrain postfix error: {ex.GetType().Name}: {ex.Message}");
                }
            }
        }

        /// <summary>
        /// Legacy int,int chunk hooks: prefetch tiles only (no full inject / no double-count).
        /// GenerateTerrainPostfix owns density rewrite when chunk object is present.
        /// </summary>
        public static void ChunkIndexPostfix(object? __instance, int __0, int __1)
        {
            try
            {
                if (ModApi.Session == null || !ModApi.Session.IsStreamed)
                    return;
                if (ModApi.Streamer == null) return;
                int blockX = __0 * ChunkTerrainSampler.VanillaChunkSize;
                int blockZ = __1 * ChunkTerrainSampler.VanillaChunkSize;
                ModApi.Session.LocalToEarth(blockX, blockZ, out int ex, out int ez);
                ModApi.Streamer.EnsureHotAround(ex, ez);
            }
            catch (Exception ex)
            {
                // Prefetch-only path: TileStreamer logs its own load failures; this logs
                // mapping/reflection failures so tiles missing forever stays debuggable.
                if (ConsumeBudget(ref _injectErrLogBudget))
                {
                    ModApi.Log($"ChunkIndex postfix error ({__0},{__1}): {ex.Message}");
                }
            }
        }

        static bool TryGetChunkIndices(object chunk, out int cx, out int cz)
        {
            cx = cz = 0;
            var t = chunk.GetType();
            // Memoized member lookups (ReflectCache): this runs on the gen thread for
            // every generated chunk; uncached GetProperty/GetField probes re-enumerate
            // type metadata each time (same results; members are process-stable).
            // X/Z properties as chunk coords or world block
            object? xObj = ReflectCache.PropPub(t, "X")?.GetValue(chunk, null)
                ?? ReflectCache.FieldPub(t, "m_X")?.GetValue(chunk)
                ?? ReflectCache.FieldPub(t, "x")?.GetValue(chunk);
            object? zObj = ReflectCache.PropPub(t, "Z")?.GetValue(chunk, null)
                ?? ReflectCache.FieldPub(t, "m_Z")?.GetValue(chunk)
                ?? ReflectCache.FieldPub(t, "z")?.GetValue(chunk);
            if (xObj == null || zObj == null)
            {
                // ChunkPos / worldPos
                var wp = ReflectCache.PropPub(t, "ChunkPos")?.GetValue(chunk, null)
                    ?? ReflectCache.FieldPub(t, "chunkPos")?.GetValue(chunk);
                if (wp != null)
                {
                    var wt = wp.GetType();
                    xObj = ReflectCache.FieldPub(wt, "x")?.GetValue(wp)
                        ?? ReflectCache.PropPub(wt, "x")?.GetValue(wp, null);
                    zObj = ReflectCache.FieldPub(wt, "z")?.GetValue(wp)
                        ?? ReflectCache.PropPub(wt, "z")?.GetValue(wp, null);
                }
            }
            if (xObj == null || zObj == null) return false;
            cx = Convert.ToInt32(xObj);
            cz = Convert.ToInt32(zObj);
            return true;
        }

    }
}
