"""Engine height constants audit: drives shipped engine_constants against live DLL."""

from pathlib import Path

import numpy as np

from realearth import DEFAULT_SEA_LEVEL_GAME_Y
from realearth.engine_constants import (
    VANILLA_3_0_1,
    audit_engine_height,
    default_game_dll,
)
from realearth.height import compress_elevation

ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = ROOT / "Source" / "RealEarth" / "EngineHeight"


def test_engine_height_module_files_exist():
    for name in (
        "EngineHeightMod.cs",
        "WorldConstantsProbe.cs",
        "AbsoluteHeightStore.cs",
        "EngineHeightPolicy.cs",
    ):
        assert (ENGINE_DIR / name).is_file(), name


def test_engine_mod_enabled_in_default_config():
    cfg = (ROOT / "Config" / "realearth.json").read_text(encoding="utf-8")
    assert "EnableEngineHeightMod" in cfg
    assert (
        '"EnableEngineHeightMod": true' in cfg or '"EnableEngineHeightMod":true' in cfg
    )
    assert '"SeaLevelGameY": 100' in cfg or '"SeaLevelGameY":100' in cfg


def test_audit_against_live_assembly_or_defaults():
    report = audit_engine_height()
    assert "constants" in report
    consts = report["constants"]
    # Stock 7DTD column height
    ydim = consts.get("ChunkBlockYDim", VANILLA_3_0_1["ChunkBlockYDim"])
    assert ydim == 256 or ydim > 256
    if ydim == 256:
        assert report["needs_engine_mod_for_taller"] is True
    # Live install should match known 3.0.1 if present
    dll = default_game_dll()
    if dll.is_file() and ydim == 256:
        assert consts.get("ChunkBlockYPow", 8) == 8
        assert consts.get("cMaxHeight", 255) == 255
        layers = consts.get("ChunkBlockLayers")
        lh = consts.get("ChunkBlockLayerHeight")
        if layers and lh:
            assert layers * lh == ydim


def test_compress_respects_custom_max_y_for_engine_policy():
    """Height path used by EngineHeightPolicy (Python twin of HeightCompress)."""
    elev = np.array([[0.0, 5000.0]])
    y = compress_elevation(elev, max_y=250, regional_exaggeration=1.0)
    assert int(y[0, 0]) == DEFAULT_SEA_LEVEL_GAME_Y
    assert int(y.max()) <= 250


def test_absolute_height_store_csharp_has_sparse_api():
    src = (ENGINE_DIR / "AbsoluteHeightStore.cs").read_text(encoding="utf-8")
    assert "SetSurfaceMeters" in src
    assert "TryGetSurfaceMeters" in src
    assert "SectionColumn" in src
