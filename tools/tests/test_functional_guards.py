"""Fail-closed guards added by the functional review pass.

Pins:
- compress_elevation never returns NaN-derived garbage (non-finite -> 0 m ASL)
- lonlat_to_block rejects non-finite input on BOTH axes (was: lon raised,
  lat silently mapped to the north pole)
- world_tile_indices_for_bbox rejects inverted/non-finite bboxes instead of
  expanding an antimeridian pair into a near-full-planet tile list
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from realearth import DEFAULT_SEA_LEVEL_GAME_Y, DEFAULT_TILE_SIZE
from realearth.coords import EarthGrid, block_to_lonlat, lonlat_to_block
from realearth.height import compress_elevation
from realearth.region import world_tile_indices_for_bbox


@pytest.mark.parametrize("profile", ["relative", "local_stretch", "linear_clamp", "one_to_one"])
def test_compress_elevation_nan_fails_closed(profile):
    elev = np.array([[np.nan, -50.0], [120.0, 8849.0]])
    out = compress_elevation(
        elev,
        sea_level_y=DEFAULT_SEA_LEVEL_GAME_Y,
        max_y=11000,
        profile=profile,
        regional_exaggeration=1.0,
    )
    assert np.isfinite(out).all()
    assert (out >= 1).all()
    # NaN cell must behave exactly like a documented 0 m ASL sample.
    expect = compress_elevation(
        np.array([[0.0, -50.0], [120.0, 8849.0]]),
        sea_level_y=DEFAULT_SEA_LEVEL_GAME_Y,
        max_y=11000,
        profile=profile,
        regional_exaggeration=1.0,
    )
    assert out[0, 0] == expect[0, 0]


def test_lonlat_to_block_rejects_nonfinite():
    with pytest.raises(ValueError):
        lonlat_to_block(float("nan"), 40.0)
    with pytest.raises(ValueError):
        lonlat_to_block(-105.0, float("nan"))
    with pytest.raises(ValueError):
        lonlat_to_block(float("inf"), float("-inf"))


def test_world_tile_indices_for_bbox_rejects_bad_bbox():
    # Antimeridian-straddling bbox given naively would hang/OOM.
    with pytest.raises(ValueError):
        world_tile_indices_for_bbox(170.0, -5.0, -170.0, 5.0)
    with pytest.raises(ValueError):
        world_tile_indices_for_bbox(float("nan"), 0.0, 10.0, 10.0)
    # Sanity: tile count matches the block span covered by the bbox.
    g = EarthGrid()
    west, south, east, north = -105.3, 39.5, -104.7, 40.0
    tiles = world_tile_indices_for_bbox(west, south, east, north, tile_size=DEFAULT_TILE_SIZE)
    x0, _ = lonlat_to_block(west, south, g)
    x1, _ = lonlat_to_block(east, north, g)
    _, zs = lonlat_to_block(west, south, g)
    _, zn = lonlat_to_block(east, north, g)
    expect_tx = max(x0, x1) // DEFAULT_TILE_SIZE - min(x0, x1) // DEFAULT_TILE_SIZE + 1
    expect_tz = max(zn, zs) // DEFAULT_TILE_SIZE - min(zn, zs) // DEFAULT_TILE_SIZE + 1
    assert len(tiles) == expect_tx * expect_tz


def test_world_tile_indices_uses_default_grid():
    g = EarthGrid()
    tiles = world_tile_indices_for_bbox(0.0, 0.0, 1e-4, 1e-4, tile_size=DEFAULT_TILE_SIZE)
    tx, tz = tiles[0]
    x, z = lonlat_to_block(0.0, 0.0, g)
    assert (tx, tz) == (x // DEFAULT_TILE_SIZE, z // DEFAULT_TILE_SIZE)
    assert math.isfinite(block_to_lonlat(x, z)[0])
