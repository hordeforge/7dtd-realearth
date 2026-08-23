"""Sliding local host window over absolute Earth coordinates.

Mirrors Source/RealEarth/WorldSession.cs continuous-travel + multiplayer origin modes:
  local ↔ absolute, longitude wrap, host fold into pack, SharedFixed / SoloSlide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from realearth.coords import EarthGrid

OriginMode = Literal["SoloSlide", "SharedFixed", "SharedSlide"]


def fold_x(x: int, width: int) -> int:
    w = max(1, width)
    r = x % w
    return r if r >= 0 else r + w


def fold_z(z: int, height: int) -> int:
    h = max(1, height)
    r = z % h
    return r if r >= 0 else r + h


@dataclass
class LocalWindow:
    """Finite engine canvas that slides over the virtual Earth grid."""

    grid: EarthGrid
    size: int = 1024
    origin_x: int = 0
    origin_z: int = 0
    enable_longitude_wrap: bool = True
    # When True (or pack is small), large host coords fold into pack [0,w)×[0,h)
    fold_host_into_pack: bool = False
    multiplayer_origin_mode: OriginMode = "SoloSlide"
    # For SharedSlide: estimate of concurrent players (1 ⇒ allow slide)
    player_count: int = 1

    def should_fold(self) -> bool:
        if self.fold_host_into_pack:
            return True
        return self.grid.width <= 65_536 and self.grid.height <= 65_536

    def should_allow_slide(self) -> bool:
        """Mirror WorldSession.ShouldAllowOriginSlide (without game probe)."""
        # Full-window single map: never slide
        if self.size >= self.grid.width and self.size >= self.grid.height:
            return False
        mode = (self.multiplayer_origin_mode or "SoloSlide").strip()
        if mode == "SharedFixed":
            return False
        if mode == "SharedSlide":
            return self.player_count <= 1
        # SoloSlide (default)
        return True

    def set_origin(self, earth_x: int, earth_z: int) -> None:
        if self.enable_longitude_wrap:
            self.origin_x = self.grid.wrap_x(earth_x)
        elif self.should_fold():
            self.origin_x = fold_x(earth_x, self.grid.width)
        else:
            self.origin_x = earth_x
        if self.should_fold() and not self.enable_longitude_wrap:
            self.origin_z = fold_z(earth_z, self.grid.height)
        else:
            self.origin_z = self.grid.clamp_z(earth_z)

    def center_on_absolute(self, earth_x: int, earth_z: int) -> None:
        if self.enable_longitude_wrap:
            earth_x = self.grid.wrap_x(earth_x)
        elif self.should_fold():
            earth_x = fold_x(earth_x, self.grid.width)
        if self.should_fold() and not self.enable_longitude_wrap:
            earth_z = fold_z(earth_z, self.grid.height)
        else:
            earth_z = self.grid.clamp_z(earth_z)
        half = self.size // 2
        ox = earth_x - half
        oz = earth_z - half
        if not self.enable_longitude_wrap:
            ox = max(0, min(max(0, self.grid.width - self.size), ox))
        oz = max(0, min(max(0, self.grid.height - self.size), oz))
        self.set_origin(ox, oz)

    def local_to_earth(self, local_x: int, local_z: int) -> tuple[int, int]:
        ex = self.origin_x + local_x
        ez = self.origin_z + local_z
        if self.enable_longitude_wrap or self.should_fold():
            ex = (
                self.grid.wrap_x(ex)
                if self.enable_longitude_wrap
                else fold_x(ex, self.grid.width)
            )
        else:
            ex = max(0, min(self.grid.width - 1, ex))
        if self.should_fold() and not self.enable_longitude_wrap:
            ez = fold_z(ez, self.grid.height)
        else:
            ez = self.grid.clamp_z(ez)
        return ex, ez

    def earth_to_local(self, earth_x: int, earth_z: int) -> tuple[int, int]:
        if self.enable_longitude_wrap or self.should_fold():
            dx = earth_x - self.origin_x
            w = max(1, self.grid.width)
            dx = ((dx % w) + w + w // 2) % w - w // 2
            local_x = dx
        else:
            local_x = earth_x - self.origin_x
        if self.should_fold() and not self.enable_longitude_wrap:
            dz = earth_z - self.origin_z
            h = max(1, self.grid.height)
            dz = ((dz % h) + h + h // 2) % h - h // 2
            local_z = dz
        else:
            local_z = earth_z - self.origin_z
        return local_x, local_z

    def tick_player_local(
        self,
        local_x: int,
        local_z: int,
        *,
        allow_slide: bool | None = None,
    ) -> tuple[bool, int, int, int, int]:
        """Drive stream focus + optional origin slide from engine-local player pos.

        Returns (slid, new_local_x, new_local_z, absolute_x, absolute_z).
        """
        earth_x, earth_z = self.local_to_earth(local_x, local_z)
        if allow_slide is None:
            allow_slide = self.should_allow_slide()
        if not allow_slide:
            return False, local_x, local_z, earth_x, earth_z

        half = self.size // 2
        margin = max(64, self.size // 6)
        center = half
        drift_x = abs(local_x - center)
        drift_z = abs(local_z - center)
        max_drift = half - margin

        if (
            drift_x > max_drift
            or drift_z > max_drift
            or local_x < margin
            or local_x > self.size - margin
            or local_z < margin
            or local_z > self.size - margin
        ):
            self.center_on_absolute(earth_x, earth_z)
            nx, nz = self.earth_to_local(earth_x, earth_z)
            nx = max(1, min(self.size - 2, nx))
            nz = max(1, min(self.size - 2, nz))
            return True, nx, nz, earth_x, earth_z

        return False, local_x, local_z, earth_x, earth_z


def stream_tile_bubble(
    earth_x: int,
    earth_z: int,
    *,
    tile_size: int = 512,
    radius: int = 2,
    tiles_x: int | None = None,
    tiles_z: int | None = None,
    wrap_x: bool = True,
) -> set[tuple[int, int]]:
    """Absolute-Earth tile indices hot around a player focus (MP overlapping bubbles)."""
    tx = earth_x // tile_size
    tz = earth_z // tile_size
    out: set[tuple[int, int]] = set()
    for dz in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x = tx + dx
            z = tz + dz
            if tiles_z is not None and (z < 0 or z >= tiles_z):
                continue
            if tiles_x is not None:
                if wrap_x:
                    x = x % tiles_x
                    if x < 0:
                        x += tiles_x
                elif x < 0 or x >= tiles_x:
                    continue
            out.add((x, z))
    return out


def multi_player_hot_tiles(
    foci: list[tuple[int, int]],
    *,
    tile_size: int = 512,
    radius: int = 2,
    tiles_x: int | None = None,
    tiles_z: int | None = None,
    wrap_x: bool = True,
) -> set[tuple[int, int]]:
    """Union of stream bubbles for all player foci (multiplayer load set)."""
    hot: set[tuple[int, int]] = set()
    for ex, ez in foci:
        hot |= stream_tile_bubble(
            ex,
            ez,
            tile_size=tile_size,
            radius=radius,
            tiles_x=tiles_x,
            tiles_z=tiles_z,
            wrap_x=wrap_x,
        )
    return hot


def tiles_to_evict(
    hot: set[tuple[int, int]],
    foci: list[tuple[int, int]],
    *,
    tile_size: int = 512,
    unload_radius: int = 5,
    tiles_x: int | None = None,
    wrap_x: bool = True,
) -> set[tuple[int, int]]:
    """Tiles outside every focus unload radius (mirrors TileStreamer multi-center eviction)."""
    keep = multi_player_hot_tiles(
        foci,
        tile_size=tile_size,
        radius=unload_radius,
        tiles_x=tiles_x,
        wrap_x=wrap_x,
    )
    return hot - keep
