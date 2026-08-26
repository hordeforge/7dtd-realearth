"""Earth lon/lat ↔ block / tile coordinates.

Equirectangular, 1 block = 1 meter at the equator for longitude and along meridians
for latitude. Longitude wraps; latitude clamps at the poles.
"""

from __future__ import annotations

import math
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
    """Convert WGS84 lon/lat (degrees) to block X/Z.

    Non-finite values raise ValueError (mirrors the CLI's usage-error guard);
    otherwise longitude wraps past +/-180 and latitude clamps at the poles.
    """
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise ValueError(f"lon/lat must be finite, got lon={lon!r} lat={lat!r}")
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
