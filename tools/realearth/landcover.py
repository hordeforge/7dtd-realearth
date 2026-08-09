"""Land cover codes → 7DTD biome colors / IDs.

Codes are our internal enum stored in .rte tiles.
"""

from __future__ import annotations

from enum import IntEnum

import numpy as np


class LandCover(IntEnum):
    OCEAN = 0
    INLAND_WATER = 1
    ICE = 2
    BARREN = 3
    GRASS = 4
    SHRUB = 5
    FOREST = 6
    WETLAND = 7
    CROPLAND = 8
    URBAN = 9
    SNOW = 10
    DESERT = 11
    UNKNOWN = 255


# Approximate mapping used when painting vanilla-style biome maps (RGB).
# Colors match common 7DTD biome map conventions (varies by version/mod).
BIOME_RGB: dict[LandCover, tuple[int, int, int]] = {
    LandCover.OCEAN: (0, 0, 255),
    LandCover.INLAND_WATER: (0, 64, 255),
    LandCover.ICE: (255, 255, 255),
    LandCover.BARREN: (128, 128, 128),
    LandCover.GRASS: (0, 128, 0),
    LandCover.SHRUB: (128, 128, 0),
    LandCover.FOREST: (0, 64, 0),
    LandCover.WETLAND: (0, 128, 128),
    LandCover.CROPLAND: (128, 255, 0),
    LandCover.URBAN: (255, 0, 0),
    LandCover.SNOW: (255, 255, 255),
    LandCover.DESERT: (255, 255, 0),
    LandCover.UNKNOWN: (0, 128, 0),
}

# Preferred vanilla biome name for each land cover (for docs / spawn rules).
BIOME_NAME: dict[LandCover, str] = {
    LandCover.OCEAN: "water",
    LandCover.INLAND_WATER: "water",
    LandCover.ICE: "snow",
    LandCover.BARREN: "wasteland",
    LandCover.GRASS: "pine_forest",
    LandCover.SHRUB: "desert",
    LandCover.FOREST: "pine_forest",
    LandCover.WETLAND: "pine_forest",
    LandCover.CROPLAND: "pine_forest",
    LandCover.URBAN: "pine_forest",
    LandCover.SNOW: "snow",
    LandCover.DESERT: "desert",
    LandCover.UNKNOWN: "pine_forest",
}


def landcover_to_biome_rgb(lc: np.ndarray) -> np.ndarray:
    """Convert landcover uint8 array → RGB uint8 (H, W, 3)."""
    arr = np.asarray(lc, dtype=np.uint8)
    h, w = arr.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for code, color in BIOME_RGB.items():
        mask = arr == int(code)
        if np.any(mask):
            rgb[mask] = color
    return rgb


def classify_from_elevation_and_lat(
    elev_m: np.ndarray,
    lat_deg: np.ndarray,
    *,
    urban_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Heuristic landcover when no external landcover raster is available.

    Good enough for demos: ocean, snow by latitude/elevation, desert bands,
    forest mid-latitudes, barren high peaks.
    """
    elev = np.asarray(elev_m, dtype=np.float64)
    lat = np.asarray(lat_deg, dtype=np.float64)
    abs_lat = np.abs(lat)
    out = np.full(elev.shape, int(LandCover.GRASS), dtype=np.uint8)

    out[elev <= 0] = LandCover.OCEAN
    land = elev > 0

    # Polar / high elevation snow
    snow = land & ((abs_lat > 60) | (elev > 3500) | ((abs_lat > 45) & (elev > 2500)))
    out[snow] = LandCover.SNOW

    # Hot arid mid-latitudes at low elevation (rough desert belt)
    desert = land & (~snow) & (abs_lat < 35) & (abs_lat > 15) & (elev < 1200)
    # exclude very wet tropics guess: near equator keep forest
    desert &= abs_lat > 12
    out[desert] = LandCover.DESERT

    # Boreal / temperate forest
    forest = land & (~snow) & (~desert) & (abs_lat < 60) & (elev < 2500)
    out[forest] = LandCover.FOREST

    # High barren
    barren = land & (elev > 2800) & (~snow)
    out[barren] = LandCover.BARREN

    if urban_mask is not None:
        out[np.asarray(urban_mask, dtype=bool) & land] = LandCover.URBAN

    return out
