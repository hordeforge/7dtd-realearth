import numpy as np

from realearth import DEFAULT_SEA_LEVEL_GAME_Y
from realearth.height import compress_elevation
from realearth.settlements import decode_poi_blob, encode_poi_blob
from realearth.tile_format import (
    EarthTile,
    Manifest,
    decode_tile,
    encode_tile,
)


def test_manifest_sea_level_default_matches_pipeline_constant():
    # Runtime (ModApi.TryApplyPackManifest) overrides SeaLevelGameY from the pack
    # manifest, so the manifest default must be the pipeline canonical constant.
    assert Manifest().sea_level_game_y == DEFAULT_SEA_LEVEL_GAME_Y
    assert Manifest.from_dict({}).sea_level_game_y == DEFAULT_SEA_LEVEL_GAME_Y


def test_tile_roundtrip():
    elev = np.linspace(-50, 2000, 64 * 64, dtype=np.float32).reshape(64, 64)
    lc = np.zeros((64, 64), dtype=np.uint8)
    lc[10:20, 10:20] = 6
    pop = np.zeros((64, 64), dtype=np.uint8)
    pop[12, 12] = 200
    poi = encode_poi_blob([{"name": "Testville", "band": "town", "local_x": 12, "local_z": 12}])
    tile = EarthTile(3, 4, elev, landcover=lc, population=pop, poi_blob=poi)
    raw = encode_tile(tile)
    back = decode_tile(raw)
    assert back.tile_x == 3 and back.tile_z == 4
    assert back.elevation_m.shape == (64, 64)
    assert abs(float(back.elevation_m.mean()) - float(elev.mean())) < 1.0
    assert back.landcover is not None and int(back.landcover[15, 15]) == 6
    assert back.population is not None and int(back.population[12, 12]) == 200
    assert decode_poi_blob(back.poi_blob)[0]["name"] == "Testville"


def test_height_sea_level():
    y = compress_elevation(np.array([[0.0, 500.0, -100.0]]))
    assert int(y[0, 0]) == DEFAULT_SEA_LEVEL_GAME_Y
    assert int(y[0, 1]) > DEFAULT_SEA_LEVEL_GAME_Y
    assert int(y[0, 2]) < DEFAULT_SEA_LEVEL_GAME_Y


def test_height_local_stretch_uses_full_band():
    # Small local range should expand toward full game band
    elev = np.array([[100.0, 120.0], [110.0, 130.0]])
    y = compress_elevation(elev, profile="local_stretch", min_y=1, max_y=250)
    assert int(y.min()) <= 20
    assert int(y.max()) >= 200


def test_height_respects_custom_max_y_for_future_engine_mod():
    elev = np.array([[0.0, 5000.0]])
    y = compress_elevation(elev, max_y=500, profile="relative", regional_exaggeration=1.0)
    assert int(y.max()) <= 500
    assert int(y[0, 0]) == DEFAULT_SEA_LEVEL_GAME_Y
