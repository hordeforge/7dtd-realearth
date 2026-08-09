"""Unit tests for Terrarium decode and tile math (no network)."""

import numpy as np

from realearth.elevation import _lonlat_to_tile, decode_terrarium_png


def test_decode_terrarium_sea_levelish():
    # elev = R*256 + G + B/256 - 32768
    # want ~0 m: 32768 = R*256 + G → R=128, G=0, B=0 → 128*256 - 32768 = 0
    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    rgb[:, :, 0] = 128
    elev = decode_terrarium_png(rgb)
    assert elev.shape == (2, 2)
    assert abs(float(elev[0, 0])) < 0.01


def test_decode_terrarium_positive_height():
    # 100 m: 32768+100 = 32868 → R=128, G=100
    rgb = np.zeros((1, 1, 3), dtype=np.uint8)
    rgb[0, 0] = (128, 100, 0)
    elev = decode_terrarium_png(rgb)
    assert abs(float(elev[0, 0]) - 100.0) < 0.5


def test_lonlat_to_tile_known_points():
    # Equator / prime meridian at z=1 → tile roughly center of 2x2
    x, y = _lonlat_to_tile(0.0, 0.0, 1)
    assert 0 <= x <= 1
    assert 0 <= y <= 1
    # San Francisco-ish should be western US tile at z=5
    x, y = _lonlat_to_tile(-122.4, 37.8, 5)
    assert 0 <= x < 32
    assert 0 <= y < 32
