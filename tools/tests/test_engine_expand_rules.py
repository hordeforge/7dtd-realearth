"""Structural rules for the Everest-scale engine height patcher (shipped source).

Does not load Mono.Cecil against the live game DLL (not in CI). Verifies the
patcher Program.cs still encodes the safety rules that fixed production crashes.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "tools" / "engine_patcher" / "Program.cs"


def _src() -> str:
    assert PATCHER.is_file(), f"missing {PATCHER}"
    return PATCHER.read_text(encoding="utf-8")


def test_everest_scale_ydim_is_16384():
    src = _src()
    # Default Everest-scale; --ydim can override at runtime
    assert "TargetYDim = 16384" in src
    assert "TargetYPow = 14" in src
    assert "--ydim" in src
    assert "SetYDim" in src


def test_layer_counts_rewritten_unconditionally_on_storage_types():
    """Mismatched alloc vs free of layer count caused native Free crashes."""
    src = _src()
    assert "IsLayerStorageType(type)" in src
    # Must not only rewrite some 64s via look-ahead that misses Dispose free sizes
    assert "replace = TargetLayers" in src
    assert "UnsafeChunkData" in src
    assert "ChunkBlockChannel" in src


def test_skips_static_ctor_and_xz_maps():
    src = _src()
    assert 'method.Name == ".cctor"' in src
    assert "IsXzMapSizeSite" in src
    assert "m_HeightMap" in src
    assert "ChunkAreaDim" in src or "XZ" in src


def test_water_volume_scales_with_ydim():
    src = _src()
    assert "TargetVolumeBits" in src
    assert "16 * 16 * TargetYDim" in src
    assert 'type.Name == "WaterDataHandle"' in src


def test_worldsession_disables_slide_on_full_window():
    ws = ROOT / "Source" / "RealEarth" / "WorldSession.cs"
    src = ws.read_text(encoding="utf-8")
    # Slide is disabled by clamping the origin when the window covers the world.
    assert "WorldWidth - LocalWindowSize" in src
    assert "SingleWorldSession" in src


def test_modlet_stock_safe_config_default():
    """YDim expand is part of RealEarth; stock compress is fallback only."""
    cfg = (ROOT / "Config" / "realearth.json").read_text(encoding="utf-8")
    assert "EngineHeightStockSafe" in cfg
    assert (ROOT / "docs" / "MODLET.md").is_file()
    assert (ROOT / "scripts" / "apply_engine_expand.sh").is_file()
    modlet = (ROOT / "docs" / "MODLET.md").read_text(encoding="utf-8")
    assert "YDim expand" in modlet
    mod = (ROOT / "Source" / "RealEarth" / "EngineHeight" / "EngineHeightMod.cs").read_text(
        encoding="utf-8"
    )
    assert "RealEarth YDim expand" in mod
    assert "OPT-IN compress on stock" in mod
