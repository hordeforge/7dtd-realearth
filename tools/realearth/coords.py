"""Earth lon/lat ↔ block / tile coordinates.

Equirectangular, 1 block = 1 meter at the equator for longitude and along meridians
for latitude. Longitude wraps; latitude clamps at the poles.
"""

from __future__ import annotations

from dataclasses import dataclass

from realearth import DEFAULT_TILE_SIZE, EARTH_CIRCUMFERENCE_M, EARTH_MERIDIAN_HALF_M


@dataclass(frozen=True, slots=True)
class EarthGrid:
    """Virtual Earth block grid parameters."""

    width: int = EARTH_CIRCUMFERENCE_M
    height: int = EARTH_MERIDIAN_HALF_M
    tile_size: int = DEFAULT_TILE_SIZE

    @property
    def tiles_x(self) -> int:
        return (self.width + self.tile_size - 1) // self.tile_size

    @property
    def tiles_z(self) -> int:
        return (self.height + self.tile_size - 1) // self.tile_size

    def wrap_x(self, x: int) -> int:
        return x % self.width

    def clamp_z(self, z: int) -> int:
        return max(0, min(self.height - 1, z))


def lonlat_to_block(lon: float, lat: float, grid: EarthGrid | None = None) -> tuple[int, int]:
    """Convert WGS84 lon/lat (degrees) to block X/Z."""
    g = grid or EarthGrid()
    if not -180.0 <= lon <= 180.0:
        lon = ((lon + 180.0) % 360.0) - 180.0
    lat = max(-90.0, min(90.0, lat))
    x = int((lon + 180.0) / 360.0 * g.width) % g.width
    z = int((90.0 - lat) / 180.0 * g.height)
    z = g.clamp_z(z)
    return x, z


def block_to_lonlat(x: int, z: int, grid: EarthGrid | None = None) -> tuple[float, float]:
    """Convert block X/Z to WGS84 lon/lat (degrees)."""
    g = grid or EarthGrid()
    x = g.wrap_x(x)
    z = g.clamp_z(z)
    lon = (x / g.width) * 360.0 - 180.0
    lat = 90.0 - (z / g.height) * 180.0
    return lon, lat


def block_to_tile(x: int, z: int, grid: EarthGrid | None = None) -> tuple[int, int]:
    g = grid or EarthGrid()
    x = g.wrap_x(x)
    z = g.clamp_z(z)
    return x // g.tile_size, z // g.tile_size


def tile_origin_block(tx: int, tz: int, grid: EarthGrid | None = None) -> tuple[int, int]:
    g = grid or EarthGrid()
    return tx * g.tile_size, tz * g.tile_size


def lonlat_bbox_to_tiles(
    west: float,
    south: float,
    east: float,
    north: float,
    grid: EarthGrid | None = None,
) -> list[tuple[int, int]]:
    """List tile indices covering a lon/lat bounding box (no antimeridian split)."""
    g = grid or EarthGrid()
    x0, z1 = lonlat_to_block(west, south, g)  # south → larger Z
    x1, z0 = lonlat_to_block(east, north, g)
    tx0, tz0 = block_to_tile(x0, z0, g)
    tx1, tz1 = block_to_tile(x1, z1, g)
    if tx1 < tx0:
        tx0, tx1 = tx1, tx0
    if tz1 < tz0:
        tz0, tz1 = tz1, tz0
    out: list[tuple[int, int]] = []
    for tz in range(tz0, tz1 + 1):
        for tx in range(tx0, tx1 + 1):
            out.append((tx, tz))
    return out


def meters_per_degree_lon(lat: float) -> float:
    """Approximate meters per degree of longitude at latitude."""
    import math

    return abs(math.cos(math.radians(lat))) * (EARTH_CIRCUMFERENCE_M / 360.0)


def meters_per_degree_lat() -> float:
    return EARTH_MERIDIAN_HALF_M / 180.0
