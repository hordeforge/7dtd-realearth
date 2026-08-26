"""Pure height inject / fail-closed policy (mirrors C# HeightInjectMath + TileSamplePolicy).

The offline product twin of HeightInjectMath.MetersToGameYOneToOne is
compress_elevation(profile="one_to_one") in realearth.height (the same function
fill_chunk_heights and the baked exports go through), so every mapping assertion
below drives that shipped code instead of a test-local copy. The C# constants are
parsed from HeightInjectMath.cs so this file's assumptions cannot drift from the
shipped mod. Structural pins that the C# delegates to the shared core live in
test_phase_cores.test_p1_height_inject_math_everest.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from realearth import (
    DEFAULT_SEA_LEVEL_GAME_Y,
    ENGINE_TARGET_MAX_Y,
)
from realearth.height import compress_elevation

ROOT = Path(__file__).resolve().parents[2]
ENGINE_HEIGHT = ROOT / "Source" / "RealEarth" / "EngineHeight" / "EngineHeightMod.cs"
SAMPLER = ROOT / "Source" / "RealEarth" / "ChunkTerrainSampler.cs"
INJECT_MATH = ROOT / "Source" / "RealEarth" / "HeightInjectMath.cs"


def _inject_math_src() -> str:
    return INJECT_MATH.read_text(encoding="utf-8")


def _csharp_const(name: str) -> int:
    m = re.search(rf"public const int {name} = (\d+);", _inject_math_src())
    assert m, f"{name} constant missing from {INJECT_MATH.name}"
    return int(m.group(1))


def one_to_one_game_y(
    elev_m: float,
    sea: int = DEFAULT_SEA_LEVEL_GAME_Y,
    max_y: int = ENGINE_TARGET_MAX_Y,
    min_y: int = 1,
) -> int:
    """Shipped offline 1 m = 1 block mapping for a single column."""
    y = compress_elevation(
        np.array([[elev_m]], dtype=np.float64),
        sea_level_y=sea,
        max_y=max_y,
        min_y=min_y,
        profile="one_to_one",
        regional_exaggeration=1.0,
    )
    return int(y[0, 0])


def test_csharp_sea_and_depth_constants_match_pipeline():
    """The mirror defaults must equal the shipped C# constants they mirror."""
    assert _csharp_const("DefaultSeaLevelGameY") == DEFAULT_SEA_LEVEL_GAME_Y == 100
    assert _csharp_const("DefaultMissingDepthBelowSea") == 8


def test_everest_one_to_one():
    # sea 100 + 8849 = 8949 under the shipped engine ceiling
    assert one_to_one_game_y(8849.0) == 8949


def test_h500_staged_peak():
    # sea 100 + 400 elev -> 500 game Y (H500 style)
    assert one_to_one_game_y(400.0) == 500


def test_byte_clamp_everest():
    """Legacy byte terrain APIs cannot hold Everest: stock 255 ceiling clamps."""
    # max_y <= 255 takes the uint8 path inside compress_elevation itself, which
    # is the offline twin of HeightInjectMath.ToByteHeight's 1..255 clamp.
    assert one_to_one_game_y(8849.0, max_y=255) == 255
    assert one_to_one_game_y(0.0, max_y=255) == 100
    # Below-floor columns clamp to min_y, never wrap to large uint8 values.
    assert one_to_one_game_y(-99.0, max_y=255) == 1


def test_fail_closed_missing_tile_is_ocean_not_peak():
    """Missing DEM must not invent land peaks (fail-closed)."""
    depth = _csharp_const("DefaultMissingDepthBelowSea")
    elev_m = -float(max(0, depth))  # MissingTileElevM contract
    gy = one_to_one_game_y(elev_m)
    assert gy == DEFAULT_SEA_LEVEL_GAME_Y - depth
    assert gy < DEFAULT_SEA_LEVEL_GAME_Y  # below sea surface
    assert gy == 92


def test_fail_closed_byte_is_not_255_land():
    depth = _csharp_const("DefaultMissingDepthBelowSea")
    b = one_to_one_game_y(-float(depth), max_y=255)
    assert b == 92
    assert b != 255


def test_sea_level_zero_elev():
    assert one_to_one_game_y(0.0) == DEFAULT_SEA_LEVEL_GAME_Y


def test_trench_clamps_at_floor_not_negative():
    """Death Valley minus 86 m at sea 100 stays >= 1 under any ceiling."""
    assert one_to_one_game_y(-420.0) == 1


def test_product_engine_height_mod_uses_tile_sample_policy():
    """Default EnableEngineHeightMod path must not bypass fail-closed policy."""
    src = ENGINE_HEIGHT.read_text(encoding="utf-8")
    assert "TileSamplePolicy.ResolveElev" in src
    assert "HeightInjectMath" in src
    # Must not only hardcode sea-8 without policy on the miss path
    assert "Math.Max(1, sea - 8)" not in src or "TileSamplePolicy" in src


def test_chunk_terrain_sampler_policy_on_non_engine_path():
    src = SAMPLER.read_text(encoding="utf-8")
    assert "TileSamplePolicy.ResolveElev" in src
    assert "SampleGameHeightIntExplicit" in src
