"""Export a tile pack into web-viewer assets (PNG mosaics + JSON)."""

from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

from realearth.landcover import landcover_to_biome_rgb
from realearth.tile_format import (
    MAX_TILE_SAMPLES,
    Manifest,
    read_manifest,
    read_tile,
    tile_path,
)

# Hostile-manifest guard: the mosaic allocates full-grid arrays, so manifest
# integers must be clamped like the binary tile header is (MAX_TILE_SAMPLES).
# 16x the single-tile ceiling admits every documented regional pack (up to
# ~16k x 16k samples) while rejecting absurd dims before np.full OOMs.
MAX_MOSAIC_SAMPLES = MAX_TILE_SAMPLES * 16
MAX_MOSAIC_TILE_SIZE = 4096


class PackMosaic(NamedTuple):
    """One pack stitched into full-resolution channels, with its manifest."""

    elevation: np.ndarray
    landcover: np.ndarray
    population: np.ndarray
    manifest: Manifest


def _hillshade(elev: np.ndarray) -> np.ndarray:
    elev = np.asarray(elev, dtype=np.float64)
    gy, gx = np.gradient(elev)
    slope = math.pi / 2 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azimuth = math.radians(315.0)
    altitude = math.radians(45.0)
    shaded = np.sin(altitude) * np.sin(slope) + np.cos(altitude) * np.cos(slope) * np.cos(
        azimuth - aspect
    )
    return np.clip(shaded, 0, 1)


def _elevation_rgb(elev: np.ndarray) -> np.ndarray:
    """Blue ocean / brown-green land ramp + hillshade."""
    elev = np.asarray(elev, dtype=np.float64)
    rgb = np.zeros(elev.shape + (3,), dtype=np.float64)
    ocean = elev <= 0
    land = ~ocean

    if np.any(ocean):
        depth = np.clip(-elev[ocean], 0, 4000) / 4000.0
        rgb[ocean, 0] = 10 + 30 * (1 - depth)
        rgb[ocean, 1] = 40 + 80 * (1 - depth)
        rgb[ocean, 2] = 90 + 140 * (1 - depth)

    if np.any(land):
        h = elev[land]
        # 0-500 green, 500-2000 brown, 2000+ white-grey
        t1 = np.clip(h / 500.0, 0, 1)
        t2 = np.clip((h - 500) / 1500.0, 0, 1)
        t3 = np.clip((h - 2000) / 3000.0, 0, 1)
        base = np.zeros((h.shape[0], 3), dtype=np.float64)
        low = h <= 500
        mid = (h > 500) & (h <= 2000)
        high = h > 2000
        if np.any(low):
            base[low] = np.stack([40 + 40 * t1[low], 90 + 100 * t1[low], 40 + 30 * t1[low]], axis=1)
        if np.any(mid):
            base[mid] = np.stack(
                [100 + 60 * t2[mid], 120 - 40 * t2[mid], 50 + 20 * t2[mid]], axis=1
            )
        if np.any(high):
            base[high] = np.stack(
                [160 + 80 * t3[high], 150 + 90 * t3[high], 140 + 100 * t3[high]], axis=1
            )
        rgb[land] = base

    shade = _hillshade(elev)
    rgb = rgb * (0.35 + 0.65 * shade[..., None])
    return np.clip(rgb, 0, 255).astype(np.uint8)


def _population_rgb(pop: np.ndarray) -> np.ndarray:
    p = np.asarray(pop, dtype=np.float64) / 255.0
    rgb = np.zeros(p.shape + (3,), dtype=np.float64)
    # dark → yellow → orange → red
    rgb[..., 0] = 20 + 235 * np.clip(p * 1.2, 0, 1)
    rgb[..., 1] = 20 + 180 * np.clip(1.0 - abs(p - 0.4) * 2, 0, 1) * (p > 0)
    rgb[..., 2] = 40 * (1 - p)
    rgb[p <= 0] = (12, 12, 18)
    return np.clip(rgb, 0, 255).astype(np.uint8)


def mosaic_pack(pack_dir: Path) -> PackMosaic:
    """Stitch all tiles in a pack into full-resolution arrays."""
    pack_dir = Path(pack_dir)
    man = read_manifest(pack_dir / "earth.manifest.json")
    if not man.tiles:
        raise ValueError("manifest has no tiles")

    ts = man.tile_size
    max_tx = max(t["tx"] for t in man.tiles)
    max_tz = max(t["tz"] for t in man.tiles)
    if ts <= 0 or ts > MAX_MOSAIC_TILE_SIZE:
        raise ValueError(f"manifest tile_size out of range (1..{MAX_MOSAIC_TILE_SIZE}): {ts}")
    if min(max_tx, max_tz) < 0 or min(man.world_width, man.world_height) < 0:
        raise ValueError("manifest tile indices and world dims must be non-negative")
    # Prefer manifest sample dimensions when present
    width = man.world_width if man.world_width > 0 else (max_tx + 1) * ts
    height = man.world_height if man.world_height > 0 else (max_tz + 1) * ts
    # Pad to tile grid for placement, then crop
    grid_w = (max_tx + 1) * ts
    grid_h = (max_tz + 1) * ts
    if grid_w * grid_h > MAX_MOSAIC_SAMPLES:
        raise ValueError(
            f"manifest implies {grid_w}x{grid_h} mosaic ({grid_w * grid_h} samples); "
            f"cap is {MAX_MOSAIC_SAMPLES}. Pack looks corrupt or hostile."
        )

    elev = np.full((grid_h, grid_w), -100.0, dtype=np.float32)
    lc = np.zeros((grid_h, grid_w), dtype=np.uint8)
    pop = np.zeros((grid_h, grid_w), dtype=np.uint8)
    loaded = 0
    missing: list[str] = []

    for entry in man.tiles:
        tx, tz = int(entry["tx"]), int(entry["tz"])
        path = tile_path(pack_dir, tx, tz)
        if not path.exists():
            missing.append(f"({tx},{tz})")
            continue
        tile = read_tile(path)
        y0, x0 = tz * ts, tx * ts
        th, tw = tile.height, tile.width
        elev[y0 : y0 + th, x0 : x0 + tw] = tile.elevation_m
        if tile.landcover is not None:
            lc[y0 : y0 + th, x0 : x0 + tw] = tile.landcover
        if tile.population is not None:
            pop[y0 : y0 + th, x0 : x0 + tw] = tile.population
        loaded += 1

    if loaded == 0:
        raise FileNotFoundError(f"no .rte tiles found under {pack_dir}")
    # Missing tiles leave -100 m (below sea level) holes that bake/export would
    # silently turn into ocean. Surface them so a broken pack is diagnosable.
    if missing:
        shown = ", ".join(missing[:10])
        more = f" … and {len(missing) - 10} more" if len(missing) > 10 else ""
        print(
            f"WARNING: {len(missing)}/{len(man.tiles)} manifest tiles missing under "
            f"{pack_dir}: {shown}{more} (those areas read as ocean)",
            file=sys.stderr,
        )

    # Crop to sample dimensions if smaller than grid
    h = min(height, grid_h)
    w = min(width, grid_w)
    return PackMosaic(
        elevation=elev[:h, :w],
        landcover=lc[:h, :w],
        population=pop[:h, :w],
        manifest=man,
    )


def export_viewer_pack(
    pack_dir: Path,
    out_dir: Path,
    *,
    max_dim: int = 2048,
    name: str | None = None,
) -> Path:
    """Write mosaics + meta for the web viewer."""
    pack_dir = Path(pack_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = mosaic_pack(pack_dir)
    elev = data.elevation
    lc = data.landcover
    pop = data.population
    man = data.manifest

    h, w = elev.shape
    scale = 1.0
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
        elev_img = Image.fromarray(elev, mode="F").resize((nw, nh), Image.Resampling.BILINEAR)
        elev_s = np.asarray(elev_img, dtype=np.float32)
        lc_s = np.asarray(
            Image.fromarray(lc, mode="L").resize((nw, nh), Image.Resampling.NEAREST),
            dtype=np.uint8,
        )
        pop_s = np.asarray(
            Image.fromarray(pop, mode="L").resize((nw, nh), Image.Resampling.BILINEAR),
            dtype=np.uint8,
        )
    else:
        elev_s, lc_s, pop_s = elev, lc, pop
        nh, nw = h, w

    elev_rgb = _elevation_rgb(elev_s)
    lc_rgb = landcover_to_biome_rgb(lc_s)
    pop_rgb = _population_rgb(pop_s)
    hybrid = (elev_rgb.astype(np.float64) * 0.55 + lc_rgb.astype(np.float64) * 0.45).astype(
        np.uint8
    )

    Image.fromarray(elev_rgb).save(out_dir / "elevation.png")
    Image.fromarray(lc_rgb).save(out_dir / "landcover.png")
    Image.fromarray(pop_rgb).save(out_dir / "population.png")
    Image.fromarray(hybrid).save(out_dir / "hybrid.png")

    # Raw elevation as 16-bit for sampling in viewer (optional)
    elev_norm = np.clip((elev_s + 500) / 4500.0 * 65535.0, 0, 65535).astype(np.uint16)
    Image.fromarray(elev_norm).save(out_dir / "elevation_raw.png")

    settlements_src = pack_dir / "settlements.json"
    settlements = []
    if settlements_src.exists():
        settlements = json.loads(settlements_src.read_text(encoding="utf-8"))
        (out_dir / "settlements.json").write_text(
            json.dumps(settlements, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # Raw .rte tiles: the viewer's "Streamed elevation" layer fetches these on
    # demand instead of a pre-made mosaic. Copied verbatim (already compressed),
    # so large packs do not need one giant mosaic.
    tiles_src = pack_dir / "tiles"
    if tiles_src.is_dir():
        tiles_dst = out_dir / "tiles"
        if tiles_dst.exists():
            shutil.rmtree(tiles_dst)
        shutil.copytree(tiles_src, tiles_dst)

    bbox = man.bbox or {"west": -180, "south": -90, "east": 180, "north": 90}
    meta = {
        "name": name or man.name,
        "version": man.version,
        "source_pack": str(pack_dir.resolve()),
        "bbox": bbox,
        "sample_width": int(w),
        "sample_height": int(h),
        "view_width": int(nw),
        "view_height": int(nh),
        "scale": scale,
        "tile_size": man.tile_size,
        "meters_per_block": man.meters_per_block,
        "world_width": man.world_width,
        "world_height": man.world_height,
        "sea_level_game_y": man.sea_level_game_y,
        "tiles": man.tiles,
        "sources": man.sources,
        "notes": man.notes,
        "layers": [
            {"id": "hybrid", "file": "hybrid.png", "label": "Hybrid"},
            {"id": "elevation", "file": "elevation.png", "label": "Elevation"},
            {"id": "landcover", "file": "landcover.png", "label": "Land cover"},
            {"id": "population", "file": "population.png", "label": "Population"},
        ],
        "settlement_count": len(settlements),
        "elev_raw": {
            "file": "elevation_raw.png",
            "offset_m": -500,
            "scale_m": 4500,
        },
    }
    (out_dir / "viewer.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return out_dir
