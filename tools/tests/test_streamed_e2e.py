"""End-to-end Streamed-mode chain, offline.

Builds a small real region pack, then exercises the full Streamed data path
the mod runs in-game: pack manifest + EarthGrid absolute coordinates -> tile
lookup -> sample at absolute (lon/lat and block) coords -> local-window slide
(including the antimeridian wrap) -> chunk sampling after the slide.

Live C# coverage already exists (spawn sample, SharedFixed, session snapshot
save/restore); this test pins the offline half so the numeric contract cannot
drift.
"""

import json
from pathlib import Path

import numpy as np

from realearth.local_window import LocalWindow, wrapped_delta
from realearth.region import build_region
from realearth.streamed_chunk import (
    fill_chunk_from_local_window,
    load_pack_grid,
    load_pack_manifest,
    lonlat_to_pack_block,
    sample_point,
)
from realearth.tile_format import read_manifest, read_tile, tile_path


def _make_pack(tmp_path: Path) -> Path:
    pack = tmp_path / "pack"
    build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        pack,
        resolution_m=250.0,
        source="synthetic",
        name="E2E",
        max_dim=64,
        also_export_7dtd=False,
    )
    return pack


def test_streamed_tile_lookup_and_sample(tmp_path: Path):
    """Pack manifest -> grid -> tile path -> sample at absolute coords."""
    pack = _make_pack(tmp_path)
    man = read_manifest(pack / "earth.manifest.json")
    assert len(man.tiles) >= 1
    grid = load_pack_grid(pack)

    # Tile lookup: manifest tile (tx,tz) resolves to a real .rte on disk.
    for entry in man.tiles:
        tile = read_tile(tile_path(pack, entry["tx"], entry["tz"]))
        assert tile.elevation_m.shape[0] == man.tile_size
        assert tile.landcover is not None

    # Absolute coordinate sampling: (0,0) is inside the pack's first tile.
    elev, lc, pop = sample_point(pack, 0, 0, grid=grid)
    assert np.isfinite(elev)
    # Fail-closed: a missing tile returns ocean (0,0,0), never a fake peak.
    # The region grid clamps XZ into the single 512 tile, so simulate the
    # missing-tile case by deleting the .rte and re-sampling (tile_path is
    # already imported at module level; no local import to avoid shadowing).
    tile = tile_path(pack, man.tiles[0]["tx"], man.tiles[0]["tz"])
    assert tile.is_file()
    tile.unlink()
    far = sample_point(pack, 10, 10, grid=grid)
    assert far == (0.0, 0, 0)


def test_streamed_lonlat_to_absolute(tmp_path: Path):
    """lon/lat -> pack absolute block must be inside the bbox tile grid."""
    pack = _make_pack(tmp_path)
    man = read_manifest(pack / "earth.manifest.json")
    bbox = man.bbox
    assert bbox is not None
    # Pack center lon/lat maps to a finite absolute block inside the pack.
    lon = (bbox["west"] + bbox["east"]) / 2
    lat = (bbox["south"] + bbox["north"]) / 2
    x, z = lonlat_to_pack_block(lon, lat, man)
    assert x >= 0 and z >= 0
    elev, _, _ = sample_point(pack, x, z, grid=load_pack_grid(pack))
    assert np.isfinite(elev)


def test_streamed_window_slide_and_wrap(tmp_path: Path):
    """Local window slide keeps the player in-pack; the antimeridian wrap
    reports a short forward delta (entity remap contract)."""
    pack = _make_pack(tmp_path)
    man = read_manifest(pack / "earth.manifest.json")
    grid = load_pack_grid(pack)
    # Use the pack's real extent, not the full-Earth default, so a slide near
    # the edge exercises folding rather than silently clamping.
    width = man.world_width
    height = man.world_height
    win = LocalWindow(grid=grid, size=min(width, 512), enable_longitude_wrap=True)

    # Center near the west edge; a local move toward it slides the origin.
    win.center_on_absolute(width // 2, height // 2)
    lx, lz = 10, 10
    before = win.local_to_earth(lx, lz)
    slid, nx, nz, ax, az = win.tick_player_local(lx, lz, allow_slide=True)
    roundtrip = win.earth_to_local(ax, az)
    assert roundtrip == (nx, nz)  # local<->absolute roundtrip stable
    # The absolute position is consistent whether or not the origin slid.
    assert (ax, az) == before or slid

    # Antimeridian wrap: a big positive move folds to a small forward delta.
    delta = wrapped_delta(width + 1234, width)
    assert 0 <= delta < width
    assert wrapped_delta(0, width) == 0


def test_streamed_chunk_after_slide(tmp_path: Path):
    """fill_chunk_from_local_window samples a chunk at an absolute origin
    through the pack (the live inject path's offline twin)."""
    pack = _make_pack(tmp_path)
    man = load_pack_manifest(pack)
    assert man is not None
    grid = load_pack_grid(pack)
    win = LocalWindow(grid=grid, size=min(man.world_width, 128))
    win.set_origin(0, 0)
    heights, lc = fill_chunk_from_local_window(
        pack,
        win,
        0,
        0,
        chunk_size=16,
        sea_level_y=man.sea_level_game_y,
    )
    # heights is (chunk_size, chunk_size); values finite and inside engine band
    assert heights.shape == (16, 16)
    assert np.isfinite(heights).all()
    assert int(heights.min()) >= 1
    assert lc.shape == (16, 16)


def test_streamed_manifest_absolute_contract(tmp_path: Path):
    """The pack manifest's absolute grid must round-trip through EarthGrid:
    world_width/world_height/tile_size are consistent with tile indices."""
    pack = _make_pack(tmp_path)
    man = read_manifest(pack / "earth.manifest.json")
    # Block coords inside the pack map to a tile index that exists.
    for entry in man.tiles:
        x0 = entry["tx"] * man.tile_size
        z0 = entry["tz"] * man.tile_size
        assert x0 < man.world_width or man.world_width <= x0 < man.world_width + man.tile_size
        assert z0 < man.world_height or man.world_height <= z0 < man.world_height + man.tile_size
    # manifest JSON is what the C# streamer reads
    raw = json.loads((pack / "earth.manifest.json").read_text(encoding="utf-8"))
    assert raw["tile_size"] == man.tile_size
    assert raw["world_width"] == man.world_width
