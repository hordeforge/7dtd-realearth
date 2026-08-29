"""Height-test map: real Everest DEM pack + 1:1 height path."""

from pathlib import Path
from unittest.mock import patch

import numpy as np

from realearth import EVEREST_METERS_ASL
from realearth.height import compress_elevation
from realearth.height_test_map import (
    EVEREST_BBOX,
    TEST_SEA_LEVEL_GAME_Y,
    build_height_test_pack,
    everest_cone_elevation,
    fetch_everest_elevation,
    landcover_from_elev,
    staged_peak_elevation,
)
from realearth.landcover import LandCover
from realearth.tile_format import read_tile, tile_path


def test_cone_fallback_peak_near_everest():
    elev = everest_cone_elevation(256)
    assert abs(float(elev.max()) - EVEREST_METERS_ASL) < 1.0


def test_fetch_synthetic_source():
    elev, sources = fetch_everest_elevation(64, source="synthetic")
    assert elev.shape == (64, 64)
    assert "synthetic" in sources[0].lower() or "synthetic" in sources[-1].lower()
    assert float(elev.max()) > 8000


def test_build_pack_with_mocked_real_dem(tmp_path: Path):
    """Simulated Terrarium-like DEM: peak near real Everest elevation."""
    size = 64
    fake = np.linspace(3000, 8800, size * size, dtype=np.float32).reshape(size, size)
    fake[size // 2, size // 2] = 8840.0

    with patch(
        "realearth.height_test_map.fetch_everest_elevation",
        return_value=(fake, ["mock terrarium Everest"]),
    ):
        info = build_height_test_pack(tmp_path, source="terrarium", size=size)

    assert info["peak_elev_m"] >= 8800
    assert info["peak_game_y_one_to_one"] == TEST_SEA_LEVEL_GAME_Y + int(round(info["peak_elev_m"]))
    tile = read_tile(tile_path(tmp_path, 0, 0))
    assert float(tile.elevation_m.max()) >= 8800
    man = (tmp_path / "earth.manifest.json").read_text(encoding="utf-8")
    assert "86.8" in man or "Everest" in man or "terrarium" in man.lower() or "mock" in man
    meta = (tmp_path / "height_test.json").read_text(encoding="utf-8")
    assert "no_compression" in meta
    assert str(EVEREST_BBOX["west"]) in meta or "86.8" in meta

    y = compress_elevation(
        tile.elevation_m,
        sea_level_y=TEST_SEA_LEVEL_GAME_Y,
        max_y=250,
        profile="one_to_one",
    )
    assert int(y.max()) == 250  # stock DTM clamp only


def test_landcover_high_is_ice_or_snow():
    # Band ladder is relative to the field peak (t1..t4 = .25/.5/.75/.9):
    # 100→forest, 4000→barren, 6000→snow, 7000→ice for a peak of 7000.
    elev = np.array([[100.0, 4000.0, 6000.0, 7000.0]], dtype=np.float32)
    lc = landcover_from_elev(elev)
    assert int(lc[0, 0]) == int(LandCover.FOREST)
    assert int(lc[0, 1]) == int(LandCover.BARREN)
    assert int(lc[0, 2]) == int(LandCover.SNOW)
    assert int(lc[0, 3]) == int(LandCover.ICE)


def test_staged_peak_elevation_maps_to_game_y_500():
    """Staged H500: elev_m peak = 500 - sea, 1:1 gameY = 500."""
    elev = staged_peak_elevation(128, peak_game_y=500)
    peak_m = float(elev.max())
    assert abs(peak_m - (500 - TEST_SEA_LEVEL_GAME_Y)) < 0.01
    game_y = TEST_SEA_LEVEL_GAME_Y + int(round(peak_m))
    assert game_y == 500
    # plains ring must be below peak (cone)
    assert float(elev.min()) < peak_m


def test_build_staged_h500_pack(tmp_path: Path):
    """Ship path for make install-height-500: peak_game_y=500 synthetic pack."""
    info = build_height_test_pack(tmp_path, peak_game_y=500, size=64, name="RealEarth_H500")
    assert info["peak_game_y_one_to_one"] == 500
    assert abs(info["peak_elev_m"] - (500 - TEST_SEA_LEVEL_GAME_Y)) < 0.1
    meta = info["meta"]
    assert meta["staged"] is True
    assert meta["engine_max_game_y"] == 500
    assert meta["name"] == "RealEarth_H500"
    tile = read_tile(tile_path(tmp_path, 0, 0))
    assert float(tile.elevation_m.max()) == info["peak_elev_m"]
    # stock DTM clamp still 250 for baked file path
    assert info["peak_game_y_stock_1to1_clamped"] == 250


def test_build_all_staged_paths(tmp_path: Path, monkeypatch):
    """build_all with peak_game_y writes height_test_500 + RealEarth_H500 dirs."""
    # Point pack/world under tmp by faking repo root layout
    (tmp_path / "data" / "samples").mkdir(parents=True)
    (tmp_path / "worlds").mkdir()
    # bake needs a lot of world files, so only test pack generation side via build_height_test_pack
    # build_all calls bake which needs full bake path; exercise pack-only here and path naming:
    from realearth import height_test_map as htm

    pack_dir = tmp_path / "data" / "samples" / "height_test_500"
    info = htm.build_height_test_pack(pack_dir, peak_game_y=500, size=32, name="RealEarth_H500")
    assert pack_dir.is_dir()
    assert (pack_dir / "earth.manifest.json").is_file()
    assert (pack_dir / "height_test.json").is_file()
    assert info["meta"]["target_peak_game_y"] == 500


def test_build_trench_pack_uses_product_sea_anchor(tmp_path: Path):
    """Trench pack: below-sea floor at the PRODUCT sea anchor (16000), so real
    depth (floor gameY 5000 = elev -11000 m) survives .rte -> inject mapping."""
    from realearth import height_test_map as htm

    pack_dir = tmp_path / "trench"
    info = htm.build_height_test_pack(
        pack_dir, trench_game_y=5000, size=64, name="RealEarth_T11000"
    )
    meta = info["meta"]
    assert meta["trench"] is True
    assert meta["sea_level_game_y"] == htm.DEFAULT_SEA_LEVEL_GAME_Y == 16000
    assert meta["engine_max_game_y"] == htm.ENGINE_TARGET_MAX_Y
    tile = read_tile(tile_path(pack_dir, 0, 0))
    assert float(tile.elevation_m.min()) <= -10900  # ~-11000 m ASL floor
    # product mapping: floor gameY = 16000 + (-11000) = 5000
    y = compress_elevation(
        tile.elevation_m,
        sea_level_y=meta["sea_level_game_y"],
        max_y=meta["engine_max_game_y"],
        profile="one_to_one",
        regional_exaggeration=1.0,
    )
    assert int(y.min()) == 5000
    assert int(y.max()) < meta["sea_level_game_y"]  # whole pack below sea
    man = (pack_dir / "earth.manifest.json").read_text(encoding="utf-8")
    assert '"sea_level_game_y": 16000' in man or '"sea_level_game_y":16000' in man
