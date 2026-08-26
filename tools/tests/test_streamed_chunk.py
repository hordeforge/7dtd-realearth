"""Streamed inject offline path: .rte sample → chunk heights (shipped streamed_chunk)."""

from pathlib import Path

import numpy as np
import pytest

from realearth.height import compress_elevation
from realearth.local_window import LocalWindow
from realearth.streamed_chunk import (
    VANILLA_CHUNK_SIZE,
    demo_pack_chunk_at_lonlat,
    fill_chunk_from_local_window,
    fill_chunk_heights,
    fill_chunk_landcover,
    load_pack_grid,
    load_pack_manifest,
    lonlat_to_pack_block,
    sample_point,
)
from realearth.tile_format import decode_tile, encode_tile, tile_path

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "data" / "samples" / "demo_region"


@pytest.fixture(scope="module")
def demo_pack() -> Path:
    assert DEMO.is_dir(), f"missing demo pack {DEMO}"
    assert (DEMO / "earth.manifest.json").is_file()
    assert tile_path(DEMO, 0, 0).is_file()
    return DEMO


def test_sample_point_reads_demo_tile(demo_pack: Path):
    elev, lc, pop = sample_point(demo_pack, 10, 10)
    # synthetic Denver foothills: not all zeros
    assert elev != 0.0 or lc != 0
    assert isinstance(lc, int)
    assert 0 <= pop <= 255


def test_fill_chunk_heights_shape_and_range(demo_pack: Path):
    h = fill_chunk_heights(demo_pack, 0, 0, chunk_size=VANILLA_CHUNK_SIZE)
    assert h.shape == (16, 16)
    # 1:1 path uses int32 when max_y > 255
    assert h.dtype in (np.uint8, np.int32)
    assert int(h.min()) >= 1
    # no compression: heights are sea + elev_m (can exceed 250)
    assert int(h.max()) >= int(h.min())
    assert int(h.mean()) >= 1


def test_fill_chunk_landcover_matches_sample(demo_pack: Path):
    lc = fill_chunk_landcover(demo_pack, 32, 32, chunk_size=16)
    _, expected, _ = sample_point(demo_pack, 32 + 5, 32 + 7)
    assert int(lc[7, 5]) == expected


def test_height_matches_one_to_one_on_sampled_elev(demo_pack: Path):
    """Fill path must use 1:1 (no compression), same as height mod."""
    from realearth import DEFAULT_SEA_LEVEL_GAME_Y, ENGINE_TARGET_MAX_Y

    ox, oz = 64, 64
    elev = np.empty((16, 16), dtype=np.float64)
    for z in range(16):
        for x in range(16):
            e, _, _ = sample_point(demo_pack, ox + x, oz + z)
            elev[z, x] = e
    expected = compress_elevation(
        elev,
        sea_level_y=DEFAULT_SEA_LEVEL_GAME_Y,
        max_y=ENGINE_TARGET_MAX_Y,
        profile="one_to_one",
        regional_exaggeration=1.0,
    )
    got = fill_chunk_heights(
        demo_pack, ox, oz, chunk_size=16, sea_level_y=DEFAULT_SEA_LEVEL_GAME_Y
    )
    np.testing.assert_array_equal(got, expected)


def test_local_window_chunk_fill(demo_pack: Path):
    g = load_pack_grid(demo_pack)
    man = load_pack_manifest(demo_pack)
    assert man is not None
    win = LocalWindow(
        grid=g, size=min(512, g.width, g.height), enable_longitude_wrap=False
    )
    win.center_on_absolute(200, 200)
    heights, lc = fill_chunk_from_local_window(demo_pack, win, 0, 0, chunk_size=16)
    assert heights.shape == (16, 16)
    assert lc.shape == (16, 16)
    # chunk earth origin should be window origin
    assert win.local_to_earth(0, 0) == (win.origin_x, win.origin_z)


def test_demo_pack_chunk_at_denver_lonlat(demo_pack: Path):
    info = demo_pack_chunk_at_lonlat(demo_pack, -104.99, 39.74)
    assert info["height_min"] >= 1
    # 1:1: mid-pack foothills can exceed stock 250
    assert info["height_mid"] >= 1
    assert info["height_max"] >= info["height_min"]
    man = load_pack_manifest(demo_pack)
    assert man is not None
    ex, ez = info["earth"]
    assert 0 <= ex < man.world_width
    assert 0 <= ez < man.world_height


def test_lonlat_to_pack_block_inside_bbox(demo_pack: Path):
    man = load_pack_manifest(demo_pack)
    assert man is not None
    x, z = lonlat_to_pack_block(-104.99, 39.74, man)
    assert 0 <= x < man.world_width
    assert 0 <= z < man.world_height


def test_rte_roundtrip_preserves_sample_for_runtime_layout(demo_pack: Path):
    """Encode/decode path shared with C# RteTile.Decode."""
    raw = tile_path(demo_pack, 0, 0).read_bytes()
    tile = decode_tile(raw)
    again = decode_tile(encode_tile(tile))
    np.testing.assert_allclose(tile.elevation_m, again.elevation_m, atol=1.0)
    if tile.landcover is not None:
        np.testing.assert_array_equal(tile.landcover, again.landcover)
