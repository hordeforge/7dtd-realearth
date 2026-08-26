"""Structural assertions on shipped C# multiplayer streaming paths.

Catches the class of bugs unit mirrors miss:
- TryPatchPlayerTick returning after EntityPlayerLocal only
- Chunk inject/sampler stomping multi-player foci via UpdateFromAbsolute(focusId=0)
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Source" / "RealEarth"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def test_try_patch_player_tick_patches_entity_player_and_local():
    """Must attempt EntityPlayer (dedicated/remote) AND EntityPlayerLocal; no early return 1."""
    src = _read("RuntimeHooks.cs")
    # Extract TryPatchPlayerTick method body
    m = re.search(
        r"static int TryPatchPlayerTick\(\)\s*\{(?P<body>.*?)"
        r"\n        static int TryPatchWorldSpawn",
        src,
        re.S,
    )
    assert m, "TryPatchPlayerTick not found"
    body = m.group("body")
    assert "EntityPlayer" in body
    assert "EntityPlayerLocal" in body
    # EntityPlayer must appear before or as co-equal target (order: base first is preferred)
    assert (
        body.index("EntityPlayer") < body.index("EntityPlayerLocal")
        or body.count("EntityPlayer") >= 2
    )
    # No early return of 1 after first successful patch
    assert "return 1;" not in body, "early return 1 would skip EntityPlayer on dedicated"
    # Must accumulate Update-path tick binds (not unload-only)
    assert "tickPatched++" in body or "patched++" in body or "patched +=" in body
    assert "return tickPatched" in body or "return patched" in body
    # Unload must not be the only counted path
    assert "PlayerTickPostfix" in body


def test_player_tick_passes_focus_id_to_session():
    """Live TickPlayerLocal call site must still pass focusId (multi-line call OK)."""
    src = _read("RuntimeHooks.cs")
    assert "TryGetEntityId" in src
    # Match TickPlayerLocal(...) that includes focusId arg (may span lines / have out dOx).
    m = re.search(
        r"TickPlayerLocal\s*\(\s*x\s*,\s*z\s*,[\s\S]*?focusId",
        src,
    )
    assert m, "TickPlayerLocal call must pass focusId (entity multi-focus)"
    # Still streams per focus into session/streamer path
    assert "focusId" in src
    assert "updateSessionAbsolute" in src  # primary-only absolute persist


def test_chunk_inject_uses_ensure_hot_not_focus_update():
    src = _read("ChunkTerrainInject.cs")
    # OnChunkGenerated samples via the shared helper; both it and the slide
    # reinject path must sync-load hot tiles and never register focus 0.
    m = re.search(
        r"public static void OnChunkGenerated\([^)]*\)\s*\{(?P<body>.*?)"
        r"\n        (?:public |static |private |$)",
        src,
        re.S,
    )
    assert m, "OnChunkGenerated not found"
    body = m.group("body")
    assert "SampleChunkColumns" in body
    assert "UpdateFromAbsolute" not in body
    h = re.search(
        r"static void SampleChunkColumns\([^)]*\)\s*\{(?P<helper>.*?)\n        \}",
        src,
        re.S,
    )
    assert h, "SampleChunkColumns helper not found"
    # Readiness race class: gen rewrite must block on tile load, not sample stale.
    assert "EnsureHotAround" in h.group("helper")
    assert "allowSyncLoad: true" in h.group("helper")
    assert "UpdateFromAbsolute" not in h.group("helper")


def test_sampler_and_engine_height_use_prefetch_sample():
    sampler = _read("ChunkTerrainSampler.cs")
    eng = _read("EngineHeight/EngineHeightMod.cs")
    # Sample paths must never register player foci (UpdateFromAbsolute stomps focus 0).
    assert "streamer.UpdateFromAbsolute" not in sampler
    assert "streamer.UpdateFromAbsolute" not in eng
    # Hot-path sampling goes through the fused single-lock prefetch sample
    # (hot tile inline; miss queues async radius-1 load, negative-cache aware).
    assert sampler.count("TrySamplePrefetch") >= 3
    assert "TrySamplePrefetch" in eng


def test_tilestreamer_has_multi_focus_and_ensure_hot():
    src = _read("TileStreamer.cs")
    assert "EnsureHotAround" in src
    assert "UpdateFromAbsolute(int earthX, int earthZ, int focusId)" in src
    assert "EvictOutsideAllFoci" in src
    assert "_foci" in src


def test_origin_slide_reinjects_loaded_chunks():
    """SoloSlide residual: loaded chunks must be rewritten under the new origin.

    Slide path must call ReinjectLoadedChunksAround after RemapAll + hot cache
    invalidation, and the reinject core must sync-load tiles (readiness race
    class) before rewriting columns via TryApplyHeightsToChunk.
    """
    src = _read("RuntimeHooks.cs")
    assert "ReinjectLoadedChunksAround" in src
    # Must run in the slide branch (after RemapAll), not on every tick.
    m = re.search(r"RemapAll\([\s\S]{0,1200}?ReinjectLoadedChunksAround", src)
    assert m, "reinject must follow RemapAll inside the origin-slide path"
    inj = _read("ChunkTerrainInject.cs")
    m = re.search(
        r"public static int ReinjectLoadedChunksAround\(.*?\n        \}",
        inj,
        re.S,
    )
    assert m, "ReinjectLoadedChunksAround missing"
    body = inj.split("ReinjectLoadedChunksAround", 1)[1]
    reinject_core = body.split("static bool ReinjectChunkObject", 1)
    assert len(reinject_core) == 2
    core = reinject_core[1].split("static IEnumerable? FindLoadedChunkCollection")[0]
    # Readiness race class: sync tile load before column rewrite. The load
    # lives in the shared SampleChunkColumns helper (same copy as gen path).
    assert "SampleChunkColumns" in core
    helper = re.search(
        r"static void SampleChunkColumns\([^)]*\)\s*\{(?P<helper>.*?)\n        \}",
        inj,
        re.S,
    )
    assert helper, "SampleChunkColumns helper not found"
    assert "allowSyncLoad: true" in helper.group("helper")
    assert "TryApplyHeightsToChunk" in core
    # Floor division for negative locals (float-to-block truncation class).
    assert "FloorDiv" in core or "FloorDiv" in inj


def test_chunk_index_hooks_are_prefetch_only():
    """ChunkIndexPostfix must stay prefetch-only (double-inject failure class).

    The broad Generate*/Fill* (int,int) bind set is intentional (fragile after
    TFP renames by design), so the postfix must never rewrite columns or touch
    foci: GenerateTerrainPostfix owns inject, player ticks own foci.
    """
    src = _read("RuntimeHooks.cs")
    m = re.search(
        r"public static void ChunkIndexPostfix\([^)]*\)\s*\{(?P<body>.*?)\n        \}",
        src,
        re.S,
    )
    assert m, "ChunkIndexPostfix not found"
    body = m.group("body")
    assert "EnsureHotAround" in body
    # Never a full column rewrite from the index hooks.
    assert "OnChunkGenerated" not in body
    assert "SampleChunkColumns" not in body
    assert "TryApplyHeightsToChunk" not in body
    # Never registers a stream focus (focus-0 stomp class).
    assert "UpdateFromAbsolute" not in body


def test_reinject_counters_are_reset_with_session():
    """Reinjected-chunk counter must reset per world so gates stay honest."""
    inj = _read("ChunkTerrainInject.cs")
    assert "SessionReinjectedChunks" in inj
    reset = re.search(
        r"public static void ResetSessionCounters\(\)\s*\{(?P<body>.*?)\n        \}",
        inj,
        re.S,
    )
    assert reset, "ResetSessionCounters not found"
    # Counters are cross-thread (gen thread vs WorldReady reset), so the reset must
    # be atomic: Interlocked.Exchange on the backing field, not a plain assignment.
    assert "Interlocked.Exchange(ref _sessionReinjectedChunks, 0)" in reset.group("body")
