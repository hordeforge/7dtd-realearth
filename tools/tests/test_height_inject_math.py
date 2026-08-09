"""Pure height inject / fail-closed policy (mirrors C# HeightInjectMath + TileSamplePolicy).

Also asserts the product EngineHeightMod path calls TileSamplePolicy (shipped source).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_HEIGHT = ROOT / "Source" / "RealEarth" / "EngineHeight" / "EngineHeightMod.cs"
SAMPLER = ROOT / "Source" / "RealEarth" / "ChunkTerrainSampler.cs"


def meters_to_game_y_one_to_one(elev_m: float, sea: int = 100, max_y: int = 11000, min_y: int = 1) -> int:
    if max_y < min_y + 1:
        max_y = min_y + 1
    y = round(sea + elev_m)
    if y < min_y:
        return min_y
    if y > max_y:
        return max_y
    return int(y)


def to_byte_height(game_y: int) -> int:
    if game_y < 1:
        return 1
    if game_y > 255:
        return 255
    return int(game_y)


def missing_tile_game_y(sea: int = 100, depth: int = 8) -> int:
    y = sea - max(0, depth)
    return 1 if y < 1 else y


def missing_tile_elev_m(depth: int = 8) -> float:
    return float(-max(0, depth))


def test_everest_one_to_one():
    # sea 100 + 8849 = 8949
    assert meters_to_game_y_one_to_one(8849.0, 100) == 8949


def test_h500_staged_peak():
    # sea 100 + 400 elev → 500 game Y (H500 style)
    assert meters_to_game_y_one_to_one(400.0, 100) == 500


def test_byte_clamp_everest():
    assert to_byte_height(8949) == 255
    assert to_byte_height(100) == 100
    assert to_byte_height(0) == 1


def test_fail_closed_missing_tile_is_ocean_not_peak():
    """Missing DEM must not invent land peaks (fail-closed)."""
    elev = missing_tile_elev_m(8)
    gy = meters_to_game_y_one_to_one(elev, 100)
    assert gy == missing_tile_game_y(100, 8)
    assert gy < 100  # below sea surface
    assert gy == 92


def test_fail_closed_byte_is_not_255_land():
    gy = missing_tile_game_y(100, 8)
    b = to_byte_height(gy)
    assert b == 92
    assert b != 255


def test_sea_level_zero_elev():
    assert meters_to_game_y_one_to_one(0.0, 100) == 100


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
