"""Structural rules for the Everest-scale engine height expand (runtime path).

The YDim expand is applied at boot by the Harmony transpiler
(RuntimeYDimTranspiler, EngineHeightRuntimePatch=true). These offline tests
pin the runtime constant targets and the switch that gates the runtime patch,
without touching a live game DLL.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_runtime_ydim_transpiler_constants():
    src = _read("Source/RealEarth/RuntimeYDimTranspiler.cs")
    # Product default = packed game-Y ceiling.
    assert "TargetYDim = 32768" in src
    assert "TargetYDimM1 = 32767" in src
    assert "TargetLayers = TargetYDim / 4" in src
    assert "TargetVolumeBits" in src
    assert "SetBlockRaw" in src
    assert "UnsafeChunkData" in src


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
    modlet = (ROOT / "docs" / "MODLET.md").read_text(encoding="utf-8")
    assert "YDim expand" in modlet
    mod = (ROOT / "Source" / "RealEarth" / "EngineHeight" / "EngineHeightMod.cs").read_text(
        encoding="utf-8"
    )
    assert "RealEarth YDim expand" in mod
    assert "OPT-IN compress on stock" in mod


def test_runtime_patch_is_config_default():
    """The runtime Harmony transpiler is the product default; the config must
    stay true and the wiring must install it before the engine-height gate."""
    import json

    cfg = json.loads((ROOT / "Config" / "realearth.json").read_text(encoding="utf-8"))
    assert cfg.get("EngineHeightRuntimePatch") is True
    assert "EngineHeightRuntimePatch" in _read("Source/RealEarth/RealEarthConfig.cs")
    modapi = _read("Source/RealEarth/ModApi.cs")
    assert "TryInstallRuntimePatch" in modapi
    assert "EngineHeightRuntimePatch" in modapi
