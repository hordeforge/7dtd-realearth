"""Engine height mod: Everest + fly-over headroom (1 m ≈ 1 block)."""

import numpy as np

from realearth import (
    DEFAULT_SEA_LEVEL_GAME_Y,
    ENGINE_TARGET_MAX_Y,
    EVEREST_METERS_ASL,
    FLY_OVER_HEADROOM_M,
)
from realearth.height import compress_elevation


def test_ceiling_is_everest_plus_fly_room():
    # 100 + 8849 + 2000 + 51 pad = 11000
    assert EVEREST_METERS_ASL == 8849
    assert FLY_OVER_HEADROOM_M == 2000
    assert DEFAULT_SEA_LEVEL_GAME_Y == 100
    assert ENGINE_TARGET_MAX_Y == 11000
    assert (
        DEFAULT_SEA_LEVEL_GAME_Y + EVEREST_METERS_ASL + FLY_OVER_HEADROOM_M + 51
        == ENGINE_TARGET_MAX_Y
    )


def test_one_to_one_everest_has_fly_headroom():
    elev = np.array([[0.0, float(EVEREST_METERS_ASL), -100.0]])
    y = compress_elevation(
        elev,
        sea_level_y=DEFAULT_SEA_LEVEL_GAME_Y,
        max_y=ENGINE_TARGET_MAX_Y,
        profile="one_to_one",
        regional_exaggeration=1.0,
    )
    assert y.dtype == np.int32
    assert int(y[0, 0]) == DEFAULT_SEA_LEVEL_GAME_Y
    everest_y = DEFAULT_SEA_LEVEL_GAME_Y + EVEREST_METERS_ASL  # 8949
    assert int(y[0, 1]) == everest_y
    # room to fly above the summit before hitting world ceiling
    fly_room = ENGINE_TARGET_MAX_Y - everest_y
    assert fly_room >= FLY_OVER_HEADROOM_M  # at least 2 km of air
    assert int(y[0, 2]) == 1  # trench clamped
    assert int(y.min()) >= 1


def test_relative_tall_band_uses_int32():
    elev = np.array([[0.0, 500.0, 8000.0]])
    y = compress_elevation(
        elev,
        sea_level_y=DEFAULT_SEA_LEVEL_GAME_Y,
        max_y=ENGINE_TARGET_MAX_Y,
        profile="relative",
        regional_exaggeration=1.0,
    )
    assert y.dtype == np.int32
    assert int(y[0, 0]) == DEFAULT_SEA_LEVEL_GAME_Y
    assert int(y[0, 1]) > DEFAULT_SEA_LEVEL_GAME_Y
    assert int(y[0, 2]) > int(y[0, 1])
    assert int(y.max()) <= ENGINE_TARGET_MAX_Y


def test_stock_250_still_uint8():
    elev = np.array([[0.0, 500.0]])
    y = compress_elevation(elev, max_y=250, profile="relative", regional_exaggeration=1.0)
    assert y.dtype == np.uint8
    assert int(y.max()) <= 250


def test_local_stretch_flat_field_honors_int32_contract():
    """Flat input takes the early-return path but must keep the documented
    dtype contract: max_y > 255 returns int32 (uint8 would wrap tall columns)."""
    elev = np.full((4, 4), 500.0)
    y = compress_elevation(
        elev,
        sea_level_y=DEFAULT_SEA_LEVEL_GAME_Y,
        max_y=ENGINE_TARGET_MAX_Y,
        profile="local_stretch",
        regional_exaggeration=1.0,
    )
    assert y.dtype == np.int32
    assert int(y[0, 0]) == DEFAULT_SEA_LEVEL_GAME_Y
    stock = compress_elevation(
        np.full((4, 4), 500.0),
        max_y=250,
        profile="local_stretch",
        regional_exaggeration=1.0,
    )
    assert stock.dtype == np.uint8
