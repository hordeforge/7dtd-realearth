"""Export a tile pack into web-viewer assets (PNG mosaics + JSON)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from realearth.landcover import landcover_to_biome_rgb
from realearth.tile_format import Manifest, read_manifest, read_tile, tile_path


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
            base[low] = np.stack(
                [40 + 40 * t1[low], 90 + 100 * t1[low], 40 + 30 * t1[low]], axis=1
            )
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


def mosaic_pack(pack_dir: Path) -> dict[str, np.ndarray]:
    """Stitch all tiles in a pack into full-resolution arrays."""
    pack_dir = Path(pack_dir)
    man = read_manifest(pack_dir / "earth.manifest.json")
    if not man.tiles:
        raise ValueError("manifest has no tiles")

    ts = man.tile_size
    max_tx = max(t["tx"] for t in man.tiles)
    max_tz = max(t["tz"] for t in man.tiles)
    # Prefer manifest sample dimensions when present
    width = man.world_width if man.world_width > 0 else (max_tx + 1) * ts
    height = man.world_height if man.world_height > 0 else (max_tz + 1) * ts
    # Pad to tile grid for placement, then crop
    grid_w = (max_tx + 1) * ts
    grid_h = (max_tz + 1) * ts

    elev = np.full((grid_h, grid_w), -100.0, dtype=np.float32)
    lc = np.zeros((grid_h, grid_w), dtype=np.uint8)
    pop = np.zeros((grid_h, grid_w), dtype=np.uint8)
    loaded = 0

    for entry in man.tiles:
        tx, tz = int(entry["tx"]), int(entry["tz"])
        path = tile_path(pack_dir, tx, tz)
        if not path.exists():
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

    # Crop to sample dimensions if smaller than grid
    h = min(height, grid_h)
    w = min(width, grid_w)
    return {
        "elevation": elev[:h, :w],
        "landcover": lc[:h, :w],
        "population": pop[:h, :w],
        "manifest": man,
    }


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
    elev = data["elevation"]
    lc = data["landcover"]
    pop = data["population"]
    man: Manifest = data["manifest"]

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
            json.dumps(settlements, indent=2) + "\n", encoding="utf-8"
        )

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
    (out_dir / "viewer.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return out_dir
