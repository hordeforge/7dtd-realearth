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
    assert body.index("EntityPlayer") < body.index("EntityPlayerLocal") or body.count(
        "EntityPlayer"
    ) >= 2
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
    # OnChunkGenerated must not call UpdateFromAbsolute (stomps focus 0)
    m = re.search(
        r"public static void OnChunkGenerated\([^)]*\)\s*\{(?P<body>.*?)"
        r"\n        (?:public |static |private |$)",
        src,
        re.S,
    )
    assert m, "OnChunkGenerated not found"
    body = m.group("body")
    assert "EnsureHotAround" in body
    assert "UpdateFromAbsolute" not in body


def test_sampler_and_engine_height_use_ensure_hot():
    sampler = _read("ChunkTerrainSampler.cs")
    eng = _read("EngineHeight/EngineHeightMod.cs")
    # Sample paths that used UpdateFromAbsolute must use EnsureHotAround
    assert sampler.count("EnsureHotAround") >= 3
    assert "streamer.UpdateFromAbsolute" not in sampler
    assert "EnsureHotAround" in eng
    assert "streamer.UpdateFromAbsolute" not in eng


def test_tilestreamer_has_multi_focus_and_ensure_hot():
    src = _read("TileStreamer.cs")
    assert "EnsureHotAround" in src
    assert "UpdateFromAbsolute(int earthX, int earthZ, int focusId)" in src
    assert "EvictOutsideAllFoci" in src
    assert "_foci" in src
