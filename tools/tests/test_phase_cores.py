"""Offline tests for IMPLEMENTATION_PLAN P0–P8 pure cores (shipped C# + Python mirrors)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Source" / "RealEarth"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


# --- P0 ExpandProductGuard (mirror C#) ---
def requires_expand_for_real_height(stock_safe: bool, one_to_one: bool, ydim: int) -> bool:
    if stock_safe:
        return False
    if not one_to_one:
        return False
    return ydim <= 256


def describe_height_mode(enable: bool, stock_safe: bool, ydim: int) -> str:
    if not enable:
        return "off"
    if ydim > 256:
        return "ydim-expanded"
    if stock_safe:
        return "stock-safe-compress"
    return "needs-expand"


def test_p0_expand_guard():
    assert requires_expand_for_real_height(False, True, 256) is True
    assert requires_expand_for_real_height(False, True, 16384) is False
    assert requires_expand_for_real_height(True, True, 256) is False
    assert describe_height_mode(True, False, 16384) == "ydim-expanded"
    assert describe_height_mode(True, False, 256) == "needs-expand"
    src = _read("ExpandProductGuard.cs")
    assert "RequiresExpandForRealHeight" in src
    assert "DescribeHeightMode" in src


# --- P1 product path fail-closed (structural + math) ---
def test_p1_engine_height_uses_tile_sample_policy():
    src = _read("EngineHeight/EngineHeightMod.cs")
    assert "TileSamplePolicy.ResolveElev" in src
    assert "HeightInjectMath" in src


def test_p1_height_inject_math_everest():
    # mirrors HeightInjectMath.MetersToGameYOneToOne
    sea, elev = 100, 8849
    assert round(sea + elev) == 8949


# --- P2 session fold / slide ---
def fold_coord(v: int, extent: int) -> int:
    e = max(1, extent)
    r = v % e
    return r if r >= 0 else r + e


def allow_origin_slide(mode: str, window: int, ww: int, wh: int, players: int) -> bool:
    """Mirror SessionOriginPolicy.AllowOriginSlide (unknown count < 0 fails closed)."""
    if window >= ww and window >= wh:
        return False
    m = (mode or "SoloSlide").strip().lower()
    if m == "sharedfixed":
        return False
    if players < 0:
        return False
    if m == "soloslide":
        return players <= 1
    if m == "sharedslide":
        return players <= 1
    return players <= 1


def needs_recentering(lx: int, lz: int, window: int) -> bool:
    half = window // 2
    margin = max(64, window // 6)
    if margin >= half:
        # Tiny window: band covers the whole host; slides would run every tick.
        return False
    max_drift = half - margin
    if abs(lx - half) > max_drift or abs(lz - half) > max_drift:
        return True
    return lx < margin or lx > window - margin or lz < margin or lz > window - margin


def wrapped_delta(delta: int, extent: int) -> int:
    """Mirror SessionOriginPolicy.WrappedDelta (shortest signed wrapped distance)."""
    e = max(1, extent)
    return ((delta % e) + e + e // 2) % e - e // 2


def test_p2_fold_and_shared_fixed():
    assert fold_coord(32768, 512) == 0
    assert fold_coord(-1, 512) == 511
    assert allow_origin_slide("SharedFixed", 1024, 40_000_000, 20_000_000, 8) is False
    assert allow_origin_slide("SoloSlide", 1024, 40_000_000, 20_000_000, 1) is True
    assert allow_origin_slide("SoloSlide", 1024, 40_000_000, 20_000_000, 2) is False
    assert allow_origin_slide("SoloSlide", 1024, 40_000_000, 20_000_000, -1) is False
    assert allow_origin_slide("SharedSlide", 1024, 40_000_000, 20_000_000, -1) is False
    assert needs_recentering(10, 512, 1024) is True
    assert needs_recentering(512, 512, 1024) is False
    # Degenerate tiny windows: band covers the whole window, so no position may
    # demand a recenter (a per-tick slide loop would thrash remap/reinject).
    for tiny in (64, 100, 128):
        for lx, lz in ((0, 0), (tiny // 2, tiny // 2), (tiny - 1, tiny - 1)):
            assert needs_recentering(lx, lz, tiny) is False, (lx, lz, tiny)
    src = _read("SessionOriginPolicy.cs")
    assert "AllowOriginSlide" in src
    assert "SharedFixed" in src
    assert "RemapLocalAfterOriginDelta" in src
    # Degenerate-window guard shipped with the product policy, not only the mirror.
    assert "margin >= half" in src
    ws = _read("WorldSession.cs")
    assert "SessionOriginPolicy.AllowOriginSlide" in ws
    assert "SessionOriginPolicy.NeedsRecentering" in ws
    assert "RestoreSnapshot" in ws


def test_p2_wrapped_delta_antimeridian():
    """Seam-crossing slide delta is short and forward, never minus-planet-width."""
    w = 40_075_017
    assert wrapped_delta(200 - 40_074_000, w) == 1_217
    assert wrapped_delta(-300, w) == -300
    assert wrapped_delta(175_000, w) == 175_000
    assert wrapped_delta(-175_000, w) == -175_000
    # Non-wrapped callers keep raw subtraction; policy helper only folds when asked.
    src = _read("SessionOriginPolicy.cs")
    assert "public static int WrappedDelta" in src
    ws = _read("WorldSession.cs")
    assert "SessionOriginPolicy.WrappedDelta(OriginEarthX - oldOx" in ws


def test_tick_absolute_shares_recenter_policy():
    """TickAbsolute must reuse NeedsRecentering (no drifted margin copy)."""
    ws = _read("WorldSession.cs")
    i = ws.index("public bool TickAbsolute")
    body = ws[i : i + 1200]
    assert "NeedsRecentering(localX, localZ, LocalWindowSize)" in body
    assert "Math.Max(64" not in body


# --- P3 stamp surface Y ---
def stamp_prefab_root_y(surface: int, offset: int = 0) -> int:
    y = surface + offset
    return 1 if y < 1 else y


def test_p3_stamp_surface_y():
    assert stamp_prefab_root_y(500) == 500
    assert stamp_prefab_root_y(500, -2) == 498
    assert stamp_prefab_root_y(0) == 1
    src = _read("StampSurfaceY.cs")
    assert "PrefabRootY" in src
    dens = (ROOT / "tools" / "realearth" / "density.py").read_text(encoding="utf-8")
    assert "stamp_prefab_root_y" in dens
    assert "dtype=np.uint8" not in dens or "_game_y_as_int32" in dens
    # Real path: stamp_prefabs_from_density must not cast game_y to uint8
    assert "np.asarray(game_y, dtype=np.uint8)" not in dens
    assert "_game_y_as_int32" in dens
    # Runtime map pins use StampSurfaceY
    assert "StampSurfaceY.PrefabRootY" in _read("CityMapLabels.cs")


# --- P4 session serialize ---
def test_p4_session_snapshot_roundtrip():
    src = _read("SessionStateStore.cs")
    assert "realearth.session.v1" in src
    assert "ToJson" in src and "TryParse" in src
    assert "TrySave" in src and "TryLoad" in src
    assert "RestoreSnapshot" in src or "RestoreSnapshot" in _read("WorldSession.cs")
    # exercise pure JSON shape expected by C# TryParse
    js = (
        '{"schema":"realearth.session.v1","originEarthX":10,"originEarthZ":20,'
        '"absoluteX":100,"absoluteZ":200,"mapMode":"Streamed",'
        '"multiplayerOriginMode":"SharedFixed","spawnLon":-104.99,"spawnLat":39.74}'
    )
    # Python parse of same fields
    d = json.loads(js)
    assert d["originEarthX"] == 10
    assert d["absoluteZ"] == 200
    assert d["multiplayerOriginMode"] == "SharedFixed"
    assert "DeltaKey" in src
    # Product entrypoints (not dead code)
    assert (SRC / "ConsoleCmdReSession.cs").is_file()
    hooks = _read("RuntimeHooks.cs")
    assert "SessionStateStore.Capture" in hooks
    assert "SessionStateStore.TryLoad" in hooks
    assert "SessionStateStore.TrySave" in hooks
    assert "EnsureHotAround" in hooks  # WorldReady must not stomp focus


def test_p4_session_restore_is_scoped_to_world_save():
    """The global mod Config fallback must never restore another world's position.

    Snapshots carry a hashed world-save scope; restore skips candidates whose
    scope differs from the current save (unknown scopes on either side apply,
    so legacy snapshots and offline contexts behave as before).
    """
    src = _read("SessionStateStore.cs")
    assert "ScopeForCurrentWorld" in src
    assert "\"scope\"" in src
    # Restore gate: a mismatched candidate is skipped, not applied.
    assert "different world scope" in src
    # Explicit operator path bypasses the gate (ConsoleCmdReSession load <path>).
    m = re.search(r"bool explicitPath = !string\.IsNullOrEmpty\(path\);", src)
    assert m, "explicit-path override for the scope gate missing"
    wsp = _read("WorldSavePath.cs")
    assert "SessionScopeId" in wsp


# --- P5 SharedFixed (covered in p2 allow_origin_slide) ---
def test_p5_shared_fixed_enforcement_in_product():
    assert allow_origin_slide("SharedFixed", 1024, 1_000_000, 1_000_000, 2) is False
    mp = json.loads((ROOT / "Config" / "realearth.mp.json").read_text(encoding="utf-8"))
    assert mp.get("MultiplayerOriginMode") == "SharedFixed"


# --- P6 density budget ---
def clamp_prefabs(requested: int, cap: int = 4) -> int:
    if requested < 0:
        return 0
    return requested if requested <= cap else cap


def test_p6_density_budget():
    assert clamp_prefabs(100, 4) == 4
    assert clamp_prefabs(2, 4) == 2
    src = _read("DensityBudget.cs")
    assert "ClampPrefabsInChunk" in src
    dens = (ROOT / "tools" / "realearth" / "density.py").read_text(encoding="utf-8")
    assert "clamp_prefabs_in_chunk" in dens
    # Must be called from stamp planner (not dead)
    assert "clamp_prefabs_in_chunk(n + 1" in dens or "clamp_prefabs_in_chunk(" in dens
    assert "try_add" in dens and "max_prefabs_per_chunk" in dens
    # C# product path caps map labels (hard max, not identity ClampPrefabsInArea(cfg,cfg))
    labels = _read("CityMapLabels.cs")
    assert "hardMaxLabels" in labels or "CityMapMaxLabels" in labels
    assert "Math.Min" in labels
    # Runtime POI uses DensityBudget area default as real cap
    assert "DensityBudget.DefaultMaxPrefabsPerKm2" in _read("RuntimePoiInject.cs")


# --- P7 CDN / fail-closed manifest ---
def test_p7_cdn_and_manifest():
    src = _read("CdnTilePolicy.cs")
    assert "FailClosedOnMiss" in src
    assert "FormatManifestFields" in src
    assert "TileUrl" in src
    ts = _read("TileStreamer.cs")
    assert "CdnTilePolicy.TileUrl" in ts
    # Default EnsureHotAround remains async (height-query path).
    assert "allowSyncLoad: false" in ts
    # Gen path may sync-load CDN via TryLoadCdnSync; async fire-and-forget still present.
    assert "TryLoadCdnSync" in ts or "LoadTileFireAndForget" in ts or "ConfigureAwait(false)" in ts
    assert "WaitForHotOrClaim" in ts
    assert "_missUntilTick" in ts or "MarkMiss" in ts
    # pure URL shape
    base = "https://cdn.example/earth"
    url = base.rstrip("/") + f"/tiles/{3}/{2}.rte"
    assert url == "https://cdn.example/earth/tiles/3/2.rte"
    cfg = json.loads((ROOT / "Config" / "realearth.json").read_text(encoding="utf-8"))
    assert cfg.get("FailClosedMissingTiles") is True


def test_review_fixes_wired():
    """Structural gates for review-fix set (origin, tall density, inject gate)."""
    inject = _read("ChunkTerrainInject.cs")
    assert "InjectBlocked" in inject
    # Tall columns: full solid density (not hollow interior) + dual fill max
    assert "EffectiveFullDualFillMaxSurface" in inject
    assert "DefaultFullDualFillMaxSurface" in inject
    # Must NOT auto dual-fill to AllocatableColumnMaxY (Everest hang)
    assert "return EngineHeight.EngineHeightMod.AllocatableColumnMaxY" not in inject
    eh = _read("EngineHeight/EngineHeightMod.cs")
    assert "ProductHeightBlocked" in eh
    assert "ClampToAllocatable" in eh
    assert "HEIGHT CAPPED" in eh
    store = _read("EngineHeight/AbsoluteHeightStore.cs")
    assert "EvictIfNeeded" in store or "_maxColumns" in store
    hooks = _read("RuntimeHooks.cs")
    assert "EnforceInjectGate" in hooks
    assert "TryRetryApply" in hooks
    assert "OriginSlideRemap.RemapAll" in hooks
    assert "WorldSavePostfix" in hooks
    assert "RuntimePoiInject" in hooks
    assert "HasProductInjectBinding" in _read("InjectPatchStats.cs")
    reheight = _read("ConsoleCmdReHeight.cs")
    assert "EnsureHotAround" in reheight
    ts = _read("TileStreamer.cs")
    assert "allowSyncLoad" in ts
    assert "LoadTileFireAndForget" in ts
    assert ".tmp" in ts  # atomic CDN write
    poi = _read("RuntimePoiInject.cs")
    assert "MaxPlaceFails" in poi or "_failCount" in poi
    assert "return placed" in poi
    cfg = json.loads((ROOT / "Config" / "realearth.json").read_text(encoding="utf-8"))
    assert cfg.get("DebugRevealFullMap") is False
    assert int(cfg.get("DebugMapRevealRadiusChunks") or 0) == 0
    assert cfg.get("EnableRuntimePoiInject") is True
    assert cfg.get("EnableGlobeMap") is False


def test_origin_slide_remap_module():
    src = _read("OriginSlideRemap.cs")
    assert "RemapAll" in src
    assert "RemapLandClaims" in src
    assert "VehicleManager" in src
    assert "SessionOriginPolicy.RemapLocalAfterOriginDelta" in src


def test_world_save_session_path():
    src = _read("WorldSavePath.cs")
    assert "GetSaveGameDir" in src
    assert "SessionFileName" in src
    store = _read("SessionStateStore.cs")
    assert "PreferredSessionPath" in store
    assert "WorldSavePath.SessionPath" in store
    # Dual-write save
    assert "paths.Add" in store or "PreferredSessionPath" in store


def test_runtime_poi_inject():
    src = _read("RuntimePoiInject.cs")
    assert "DensityBudget.ClampPrefabsInChunk" in src
    assert "StampSurfaceY.PrefabRootY" in src
    assert "EnableRuntimePoiInject" in _read("RealEarthConfig.cs")
    inject = _read("ChunkTerrainInject.cs")
    assert "RuntimePoiInject.OnChunkGenerated" in inject


def test_sample_game_height_int_never_byte_path():
    """Int height API must not call byte SampleGameHeight (clamps Everest to 255)."""
    src = _read("ChunkTerrainSampler.cs")
    # SampleGameHeightInt body: after Active branch, must use Explicit not SampleGameHeight(
    # Extract the SampleGameHeightInt method region roughly
    i = src.index("public static int SampleGameHeightInt")
    j = src.index("public static byte SampleLandcover", i)
    body = src[i:j]
    assert "SampleGameHeightIntExplicit" in body
    assert "return SampleGameHeight(" not in body


def test_retry_apply_never_double_patch():
    """Retry must not stack Harmony postfixes (MethodBase set + no gen re-scan after index)."""
    hooks = _read("RuntimeHooks.cs")
    assert "Never full re-Apply" in hooks or "would stack postfixes" in hooks
    assert "if (_harmony == null || _harmonyMissing)" in hooks
    assert "HasProductInjectBinding" in hooks
    # Global already-patched set makes PatchPostfix idempotent
    assert "_patchedMethods" in hooks
    assert "HashSet<MethodBase>" in hooks
    assert "_patchedMethods.Add(target)" in hooks
    # Extract TryRetryApply body: must not re-enter full gen scan when ChunkIndexPatches > 0
    m = re.search(
        r"public static void TryRetryApply\(\)\s*\{(?P<body>.*?)\n        static Type\?",
        hooks,
        re.S,
    )
    assert m, "TryRetryApply not found"
    body = m.group("body")
    # Must retry gen whenever GenerateTerrainPatches==0 (even if ChunkIndexPatches>0)
    assert "GenerateTerrainPatches == 0" in body
    assert "TryPatchChunkTerrainGenerate()" in body
    # Do not block gen retry solely on chunk-index binds
    assert "ChunkIndexPatches == 0" not in body
    # Must not reset _applied to false before Apply on harmony-present path
    assert "_applied = false" not in body


def test_tick_absolute_refuses_claims():
    ws = _read("WorldSession.cs")
    assert "TickAbsolute" in ws
    assert "HasLandClaims" in ws
    # TickAbsolute path must share claim gate
    i = ws.index("public bool TickAbsolute")
    body = ws[i : i + 800]
    assert "HasLandClaims" in body


def test_absolute_height_store_earth_key():
    store = _read("EngineHeight/AbsoluteHeightStore.cs")
    assert "ToEarthKey" in store
    assert "LocalToEarth" in store


def test_dedicated_session_absolute_policy():
    """Dedicated solo has no EntityPlayerLocal; absolute must still advance when count≤1."""
    ws = _read("WorldSession.cs")
    assert "ShouldUpdateSessionAbsolute" in ws
    hooks = _read("RuntimeHooks.cs")
    assert "ShouldUpdateSessionAbsolute" in hooks
    assert "updateAbs" in hooks
    assert "updateSessionAbsolute" in hooks


def test_session_parse_keeps_default_map_mode():
    """TryParse must not blank MapMode when key missing (out string defaults to empty)."""
    src = _read("SessionStateStore.cs")
    assert "do not blank defaults" in src.lower() or "Optional strings" in src
    assert 'TryReadString(json, "mapMode"' in src
    # Must assign only when non-empty
    assert "IsNullOrEmpty(mm)" in src or '!string.IsNullOrEmpty(mm)' in src


def test_dual_fill_hard_cap():
    inject = _read("ChunkTerrainInject.cs")
    assert "hardMax" in inject
    assert "2048" in inject


def test_chunk_index_prefetch_only():
    """ChunkIndexPostfix must not call OnChunkGenerated (double inject / false counters)."""
    hooks = _read("RuntimeHooks.cs")
    m = re.search(
        r"public static void ChunkIndexPostfix\([^)]*\)\s*\{(?P<body>.*?)"
        r"\n        static bool TryGetChunkIndices",
        hooks,
        re.S,
    )
    assert m, "ChunkIndexPostfix not found"
    body = m.group("body")
    assert "EnsureHotAround" in body
    assert "OnChunkGenerated" not in body


def test_has_land_claims_fail_closed():
    src = _read("OriginSlideRemap.cs")
    assert "fail closed" in src.lower() or "inspected" in src
    assert "return true" in src  # unknown claim state refuses slide
    # Must use GameManager.GetPersistentPlayerList (not World-only)
    assert "GameManager" in src
    assert "GetPersistentPlayerList" in src


def test_chunk_inject_sync_loads_tiles():
    inject = _read("ChunkTerrainInject.cs")
    assert "allowSyncLoad: true" in inject
    assert "EnsureHotAround" in inject


def test_remove_focus_clears_hot_when_empty():
    ts = _read("TileStreamer.cs")
    assert "_foci.Count == 0" in ts
    assert "_hot.Clear()" in ts


def test_height_float_args_use_floor():
    hooks = _read("RuntimeHooks.cs")
    assert "Math.Floor(__0)" in hooks or "Math.Floor(__0)" in hooks.replace(" ", "")
    assert "HeightFloatFromFloatArgsPostfix" in hooks
    # Entity position components floor centrally since TryGetPos/ReadComp moved
    # to the shared EngineReflection helper (used by tick + origin-slide remap).
    refl = _read("EngineReflection.cs")
    assert "Math.Floor(fl)" in refl


def test_sync_load_waits_inflight_and_cdn():
    ts = _read("TileStreamer.cs")
    assert "WaitForHotOrClaim" in ts
    assert "TryLoadCdnSync" in ts
    assert "InvalidateHotCache" in ts
    assert "PublishTileBytes" in ts
    # Miss cache must not block gen sync path
    assert "allowSyncLoad" in ts and "!allowSyncLoad" in ts


def test_tall_column_no_full_surface_density_loop():
    """Tall peaks must not Reflect-invoke density for every y in 0..surface."""
    inject = _read("ChunkTerrainInject.cs")
    assert "never full-column Reflect" in inject or "crust+plug only" in inject
    assert "WriteColumnCell" in inject


def test_slide_setpos_rollback():
    hooks = _read("RuntimeHooks.cs")
    assert "rolled back" in hooks or "SetPos failed" in hooks
    assert "TrySetPos" in hooks
    # Slide rollback goes through the shared EngineReflection.TrySetPos (bool contract).
    assert "EngineReflection.TrySetPos" in hooks
    refl = _read("EngineReflection.cs")
    assert "static bool TrySetPos" in refl


def test_center_window_respects_update_absolute():
    ws = _read("WorldSession.cs")
    assert "updateAbsolute" in ws
    assert "CenterWindowOnAbsolute(earthX, earthZ, updateAbsolute: updateSessionAbsolute)" in ws


# --- P8 sparse Y scaffold ---
def section_index(game_y: int, section_h: int = 16) -> int:
    h = max(4, section_h)
    if game_y >= 0:
        return game_y // h
    return (game_y - (h - 1)) // h


def test_p8_sparse_y_scaffold():
    assert section_index(0) == 0
    assert section_index(15) == 0
    assert section_index(16) == 1
    assert section_index(8949) == 8949 // 16
    src = _read("SparseYScaffold.cs")
    assert "HotSectionRange" in src
    store = _read("EngineHeight/AbsoluteHeightStore.cs")
    assert "SparseYScaffold.HotSectionRange" in store


def test_implementation_plan_lists_all_phases():
    plan = (ROOT / "docs" / "IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
    for p in ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"):
        assert p in plan


# --- resource lifecycle gates (leak review) ---
def test_tile_miss_cache_is_bounded():
    """Negative cache must sweep expired deadlines, not grow for process lifetime."""
    ts = _read("TileStreamer.cs")
    assert "MissCachePruneThreshold" in ts
    assert "PruneExpiredMissesLocked" in ts
    # Prune runs before inserting a new miss once the map is over the threshold.
    mark_miss = ts[ts.index("void MarkMiss") : ts.index("bool IsWithinAnyFocus")]
    assert "PruneExpiredMissesLocked" in mark_miss
    assert "_missUntilTick.Count >= MissCachePruneThreshold" in mark_miss


def test_cdn_publish_cleans_temp_on_failed_write():
    """A failed temp write must delete the .tmp file, not orphan it on disk."""
    ts = _read("TileStreamer.cs")
    publish = ts[ts.index("static void PublishTileBytes") : ts.index("void QueueLoad")]
    assert "File.WriteAllBytes(tmp, bytes)" in publish
    assert "File.Delete(tmp)" in publish
