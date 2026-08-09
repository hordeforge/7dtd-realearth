"""Map real elevation (meters ASL) into 7DTD game Y.

Stock ceiling ~255. RealEarth engine-height mod targets ENGINE_TARGET_MAX_Y (11000; sea 100 + Everest + fly room)
with optional 1 m = 1 block (profile one_to_one). .rte keeps real meters; mapping
happens when writing game terrain / inject.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from realearth import DEFAULT_SEA_LEVEL_GAME_Y, ENGINE_TARGET_MAX_Y, GAME_MAX_Y

HeightProfile = Literal["relative", "local_stretch", "linear_clamp", "one_to_one"]


def compress_elevation(
    elev_m: np.ndarray,
    *,
    sea_level_y: int = DEFAULT_SEA_LEVEL_GAME_Y,
    max_y: int = GAME_MAX_Y - 5,
    min_y: int = 1,
    land_headroom: int = 5,
    regional_exaggeration: float = 1.35,
    profile: HeightProfile = "relative",
) -> np.ndarray:
    """Map real meters ASL into game block heights.

    Profiles:
      relative — piecewise ASL curve + optional detail exaggeration (default, stock)
      local_stretch — map this array's min..max into [min_y, max_y]
      linear_clamp — elev_m/scale into Y then clamp
      one_to_one - product mapping: sea_level_y + elev_m (1 m = 1 block); use max_y=11000 for Everest

    When max_y > 255 returns int32; otherwise uint8 (stock columns).
    """
    elev = np.asarray(elev_m, dtype=np.float64)
    max_y = int(min(max(max_y, min_y + 1), ENGINE_TARGET_MAX_Y))
    out_dtype = np.int32 if max_y > 255 else np.uint8

    if profile == "one_to_one":
        y = sea_level_y + elev
        return np.clip(np.rint(y), min_y, max_y).astype(out_dtype)

    if profile == "local_stretch":
        return _local_stretch(elev, min_y=min_y, max_y=max_y, sea_level_y=sea_level_y).astype(out_dtype)
    if profile == "linear_clamp":
        scale_m_per_block = 1.0 if max_y > 255 else 40.0
        y = sea_level_y + elev / scale_m_per_block
        return np.clip(np.rint(y), min_y, max_y).astype(out_dtype)

    # --- relative (default) ---
    out = np.empty_like(elev, dtype=np.float64)
    sea = elev <= 0
    land = ~sea

    if np.any(sea):
        depth = -elev[sea]
        shallow = np.clip(depth, 0, 200) / 200.0
        deep = np.clip(depth - 200, 0, 10_000) / 10_000.0
        drop = shallow * 14.0 + deep * (sea_level_y - min_y - 14)
        out[sea] = sea_level_y - drop

    if np.any(land):
        h = elev[land]
        y = np.empty_like(h)
        band1 = h <= 500
        band2 = (h > 500) & (h <= 3000)
        band3 = h > 3000

        if max_y > 255:
            y_low_end = sea_level_y + max(48, max_y // 16)
            y_mid_end = sea_level_y + max(148, max_y // 3)
            y_high_end = max_y - min(land_headroom, max_y // 100)
        else:
            y_low_end = sea_level_y + 48
            y_mid_end = sea_level_y + 148
            y_high_end = max_y - land_headroom

        if np.any(band1):
            t = h[band1] / 500.0
            y[band1] = sea_level_y + t * (y_low_end - sea_level_y)
        if np.any(band2):
            t = (h[band2] - 500.0) / 2500.0
            y[band2] = y_low_end + t * (y_mid_end - y_low_end)
        if np.any(band3):
            t = np.clip((h[band3] - 3000.0) / 6000.0, 0, 1)
            t = 1.0 - (1.0 - t) ** 1.4
            y[band3] = y_mid_end + t * (y_high_end - y_mid_end)

        out[land] = y

    if regional_exaggeration != 1.0 and out.size > 4 and max_y <= 255:
        try:
            from numpy.lib.stride_tricks import sliding_window_view

            k = 9
            pad = k // 2
            padded = np.pad(out, pad, mode="edge")
            windows = sliding_window_view(padded, (k, k))
            low = windows.mean(axis=(-1, -2))
            detail = out - low
            out = low + detail * regional_exaggeration
        except Exception:
            pass

    return np.clip(np.rint(out), min_y, max_y).astype(out_dtype)


def _local_stretch(
    elev: np.ndarray,
    *,
    min_y: int,
    max_y: int,
    sea_level_y: int,
) -> np.ndarray:
    """Maximize relief inside this array: min elev → min_y, max → max_y; sea stays near sea_level_y."""
    elev = np.asarray(elev, dtype=np.float64)
    lo = float(np.nanmin(elev))
    hi = float(np.nanmax(elev))
    if hi <= lo + 1e-6:
        return np.full(elev.shape, sea_level_y, dtype=np.uint8)
    # Keep sea level fixed-ish: map 0 m to sea_level_y when range crosses 0
    if lo < 0 < hi:
        out = np.empty_like(elev)
        sea = elev <= 0
        land = ~sea
        if np.any(sea):
            t = (elev[sea] - lo) / (0.0 - lo + 1e-9)
            out[sea] = min_y + t * (sea_level_y - min_y)
        if np.any(land):
            t = elev[land] / (hi + 1e-9)
            out[land] = sea_level_y + t * (max_y - sea_level_y)
        return np.clip(np.rint(out), min_y, max_y).astype(np.uint8)
    t = (elev - lo) / (hi - lo)
    dtype = np.int32 if max_y > 255 else np.uint8
    return np.clip(np.rint(min_y + t * (max_y - min_y)), min_y, max_y).astype(dtype)


def to_heightmap_png_array(game_y: np.ndarray) -> np.ndarray:
    """16-bit grayscale array for 7DTD custom heightmap importers (0-65535).

    Many importers expect 16-bit PNG where value maps into game height.
    We map game Y 0-255 → 0-65535 linearly.
    """
    y = np.asarray(game_y, dtype=np.float64)
    return np.clip(y / 255.0 * 65535.0, 0, 65535).astype(np.uint16)
