"""Streamed chunk terrain fill from offline .rte packs.

This is the offline counterpart of Source/RealEarth/ChunkTerrainSampler:
pack XZ (or local window → pack) → tile sample → compress → 16×16 heights.

Regional demo packs use local 0-based tiles + small world_width/height.
Full-planet packs use absolute EarthGrid indices.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from realearth import DEFAULT_SEA_LEVEL_GAME_Y, ENGINE_TARGET_MAX_Y
from realearth.coords import EarthGrid, block_to_tile, lonlat_to_block
from realearth.height import compress_elevation
from realearth.local_window import LocalWindow
from realearth.tile_format import Manifest, read_manifest, read_tile, tile_path

VANILLA_CHUNK_SIZE = 16


def load_pack_manifest(pack_dir: Path) -> Manifest | None:
    man_path = Path(pack_dir) / "earth.manifest.json"
    if man_path.is_file():
        return read_manifest(man_path)
    return None


def load_pack_grid(pack_dir: Path) -> EarthGrid:
    m = load_pack_manifest(pack_dir)
    if m is not None:
        return EarthGrid(width=m.world_width, height=m.world_height, tile_size=m.tile_size)
    return EarthGrid()


def lonlat_to_pack_block(lon: float, lat: float, manifest: Manifest) -> tuple[int, int]:
    """Map WGS84 lon/lat into pack-local block XZ using manifest bbox (or full Earth)."""
    g = EarthGrid(
        width=manifest.world_width,
        height=manifest.world_height,
        tile_size=manifest.tile_size,
    )
    bbox = manifest.bbox
    if not bbox:
        # full Earth equirectangular
        return lonlat_to_block(lon, lat, g)
    west = float(bbox["west"])
    south = float(bbox["south"])
    east = float(bbox["east"])
    north = float(bbox["north"])
    if east <= west or north <= south:
        raise ValueError("invalid pack bbox")
    # clamp into bbox
    lon = max(west, min(east, lon))
    lat = max(south, min(north, lat))
    fx = (lon - west) / (east - west)
    fz = (north - lat) / (north - south)  # z increases southward
    x = int(fx * (manifest.world_width - 1))
    z = int(fz * (manifest.world_height - 1))
    x = (
        g.wrap_x(x)
        if manifest.world_width > 10_000_000
        else max(0, min(manifest.world_width - 1, x))
    )
    return x, g.clamp_z(z)


def sample_point(
    pack_dir: Path,
    earth_x: int,
    earth_z: int,
    *,
    grid: EarthGrid | None = None,
    sea_level_y: int = DEFAULT_SEA_LEVEL_GAME_Y,
    cache: dict[tuple[int, int], object] | None = None,
) -> tuple[float, int, int]:
    """Sample (elevation_m, landcover, population) at pack/Earth block XZ.

    Missing tile → elevation 0, landcover 0 (ocean), population 0.
    Layout: pack_dir/tiles/{tz}/{tx}.rte (same as C# TileStreamer.TileFilePath).
    """
    pack_dir = Path(pack_dir)
    g = grid or load_pack_grid(pack_dir)
    # Regional packs are small; full Earth wraps X
    earth_x = (
        g.wrap_x(earth_x)
        if g.width > 10_000_000
        else max(0, min(g.width - 1, earth_x))
    )
    earth_z = g.clamp_z(earth_z)
    tx, tz = block_to_tile(earth_x, earth_z, g)
    key = (tx, tz)
    store = cache if cache is not None else {}
    if key not in store:
        p = tile_path(pack_dir, tx, tz)
        store[key] = read_tile(p) if p.is_file() else None
    tile = store[key]
    if tile is None:
        return 0.0, 0, 0
    lx = earth_x - tx * g.tile_size
    lz = earth_z - tz * g.tile_size
    # Clamp into tile in case edge world size < tile grid
    h, w = tile.elevation_m.shape
    if lx < 0 or lz < 0 or lx >= w or lz >= h:
        return 0.0, 0, 0
    elev = float(tile.elevation_m[lz, lx])
    lc = int(tile.landcover[lz, lx]) if tile.landcover is not None else 255
    pop = int(tile.population[lz, lx]) if tile.population is not None else 0
    return elev, lc, pop


def fill_chunk_heights(
    pack_dir: Path,
    chunk_earth_origin_x: int,
    chunk_earth_origin_z: int,
    *,
    chunk_size: int = VANILLA_CHUNK_SIZE,
    sea_level_y: int = DEFAULT_SEA_LEVEL_GAME_Y,
    grid: EarthGrid | None = None,
    cache: dict[tuple[int, int], object] | None = None,
) -> np.ndarray:
    """Fill chunk_size² game heights from .rte samples (pack/Earth origin).

    Returns int32 array shape (chunk_size, chunk_size), row=z, col=x (1:1
    heights exceed the uint8 range once max_y > 255). Pass a shared ``cache``
    when filling several channels of the same chunk so each overlapping tile
    is read and inflated once.
    """
    pack_dir = Path(pack_dir)
    g = grid or load_pack_grid(pack_dir)
    store = cache if cache is not None else {}
    elev = np.empty((chunk_size, chunk_size), dtype=np.float64)
    for z in range(chunk_size):
        for x in range(chunk_size):
            e, _, _ = sample_point(
                pack_dir,
                chunk_earth_origin_x + x,
                chunk_earth_origin_z + z,
                grid=g,
                sea_level_y=sea_level_y,
                cache=store,
            )
            elev[z, x] = e
    # No compression: 1 m = 1 block (same as engine height mod)
    return compress_elevation(
        elev,
        sea_level_y=sea_level_y,
        max_y=ENGINE_TARGET_MAX_Y,
        profile="one_to_one",
        regional_exaggeration=1.0,
    )


def fill_chunk_landcover(
    pack_dir: Path,
    chunk_earth_origin_x: int,
    chunk_earth_origin_z: int,
    *,
    chunk_size: int = VANILLA_CHUNK_SIZE,
    grid: EarthGrid | None = None,
    cache: dict[tuple[int, int], object] | None = None,
) -> np.ndarray:
    pack_dir = Path(pack_dir)
    g = grid or load_pack_grid(pack_dir)
    store = cache if cache is not None else {}
    out = np.zeros((chunk_size, chunk_size), dtype=np.uint8)
    for z in range(chunk_size):
        for x in range(chunk_size):
            _, lc, _ = sample_point(
                pack_dir,
                chunk_earth_origin_x + x,
                chunk_earth_origin_z + z,
                grid=g,
                cache=store,
            )
            out[z, x] = lc
    return out


def fill_chunk_from_local_window(
    pack_dir: Path,
    window: LocalWindow,
    chunk_local_origin_x: int,
    chunk_local_origin_z: int,
    *,
    chunk_size: int = VANILLA_CHUNK_SIZE,
    sea_level_y: int = DEFAULT_SEA_LEVEL_GAME_Y,
) -> tuple[np.ndarray, np.ndarray]:
    """Map local chunk corner through window → absolute Earth → heights + landcover."""
    ex, ez = window.local_to_earth(chunk_local_origin_x, chunk_local_origin_z)
    # One decode cache for both channels: a 16x16 chunk spans up to 2x2 tiles and
    # each would otherwise be read + inflated twice.
    tile_cache: dict[tuple[int, int], object] = {}
    heights = fill_chunk_heights(
        pack_dir,
        ex,
        ez,
        chunk_size=chunk_size,
        sea_level_y=sea_level_y,
        grid=window.grid,
        cache=tile_cache,
    )
    lc = fill_chunk_landcover(
        pack_dir, ex, ez, chunk_size=chunk_size, grid=window.grid, cache=tile_cache
    )
    return heights, lc


def demo_pack_chunk_at_lonlat(
    pack_dir: Path,
    lon: float,
    lat: float,
    *,
    chunk_size: int = VANILLA_CHUNK_SIZE,
    sea_level_y: int = DEFAULT_SEA_LEVEL_GAME_Y,
) -> dict:
    """Center a local window on lon/lat (pack bbox mapping) and fill one center chunk."""
    pack_dir = Path(pack_dir)
    man = load_pack_manifest(pack_dir)
    if man is None:
        raise FileNotFoundError(f"no earth.manifest.json in {pack_dir}")
    g = EarthGrid(width=man.world_width, height=man.world_height, tile_size=man.tile_size)
    sea = man.sea_level_game_y if man.sea_level_game_y else sea_level_y
    ex, ez = lonlat_to_pack_block(lon, lat, man)
    # Window cannot exceed pack; clamp size
    win_size = min(1024, man.world_width, man.world_height)
    # Regional packs: no longitude wrap (small canvas)
    wrap = man.world_width > 10_000_000
    win = LocalWindow(grid=g, size=win_size, enable_longitude_wrap=wrap)
    win.center_on_absolute(ex, ez)
    half = win.size // 2
    cx = (half // chunk_size) * chunk_size
    cz = (half // chunk_size) * chunk_size
    heights, lc = fill_chunk_from_local_window(
        pack_dir, win, cx, cz, chunk_size=chunk_size, sea_level_y=sea
    )
    return {
        "lon": lon,
        "lat": lat,
        "earth": (ex, ez),
        "origin": (win.origin_x, win.origin_z),
        "chunk_local": (cx, cz),
        "chunk_earth": win.local_to_earth(cx, cz),
        "height_min": int(heights.min()),
        "height_max": int(heights.max()),
        "height_mid": int(heights[chunk_size // 2, chunk_size // 2]),
        "landcover_mid": int(lc[chunk_size // 2, chunk_size // 2]),
        "heights": heights,
        "landcover": lc,
    }
