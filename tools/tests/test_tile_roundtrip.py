import struct
import zlib

import numpy as np

from realearth import DEFAULT_SEA_LEVEL_GAME_Y
from realearth.height import compress_elevation
from realearth.settlements import decode_poi_blob, encode_poi_blob
from realearth.tile_format import (
    HEADER_STRUCT,
    MAX_TILE_SAMPLES,
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


def test_elevation_u16_rounds_to_nearest_meter():
    # Terrarium decodes carry B/256 fractions; packing must round (not truncate)
    # so stored meters match the sampled surface on a 1 m = 1 block product.
    from realearth.tile_format import _elevation_to_u16, _u16_to_elevation

    elev = np.array([[123.25, 123.75], [-10999.5, 8849.0]], dtype=np.float32)
    back = _u16_to_elevation(_elevation_to_u16(elev))
    assert back[0, 0] == np.float32(123.0)  # 123.25 → nearest is 123
    assert back[0, 1] == np.float32(124.0)  # 123.75 must not truncate to 123
    assert back[1, 1] == np.float32(8849.0)


def test_elevation_u16_nan_fails_closed_to_zero_meters():
    from realearth.tile_format import _elevation_to_u16, _u16_to_elevation

    elev = np.array([[np.nan, 500.0]], dtype=np.float32)
    back = _u16_to_elevation(_elevation_to_u16(elev))
    assert float(back[0, 0]) == 0.0  # matches C# missing-sample placeholder elev
    assert float(back[0, 1]) == 500.0


def _hostile_header(w: int, h: int, flags: int) -> bytes:
    return HEADER_STRUCT.pack(b"RTE1", 0, 0, 1, flags, w, h, 0)


def test_decode_rejects_hostile_dims():
    # Header claims a tile far beyond MAX_TILE_SAMPLES: must fail fast, not allocate.
    raw = _hostile_header(1 << 20, 1 << 20, 0)
    try:
        decode_tile(raw)
        raise AssertionError("expected ValueError for oversized dims")
    except ValueError:
        pass
    # High-bit dims read as negative int32 by the C# runtime decoder.
    try:
        decode_tile(_hostile_header(1 << 31, 64, 0))
        raise AssertionError("expected ValueError for high-bit dims")
    except ValueError:
        pass


def test_decode_rejects_decompression_bomb():
    # A tiny compressed section that would inflate to gigabytes must be refused.
    bomb = zlib.compress(b"\x00" * (MAX_TILE_SAMPLES * 8), level=6)
    raw = _hostile_header(2, 2, 0) + struct.pack("<I", len(bomb)) + bomb
    try:
        decode_tile(raw)
        raise AssertionError("expected ValueError for decompression bomb")
    except ValueError:
        pass


def test_decode_rejects_truncated_and_oversized_section_lengths():
    body = _hostile_header(2, 2, 0) + struct.pack("<I", 1 << 30)
    try:
        decode_tile(body)
        raise AssertionError("expected ValueError for section length beyond buffer")
    except ValueError:
        pass
    short = _hostile_header(2, 2, 0) + b"\x00\x00"  # truncated length prefix
    try:
        decode_tile(short)
        raise AssertionError("expected ValueError for truncated header")
    except ValueError:
        pass
