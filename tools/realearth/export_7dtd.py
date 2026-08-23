"""Export heightmaps / biomes compatible with 7DTD custom map workflows."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from realearth.height import compress_elevation, to_heightmap_png_array
from realearth.landcover import landcover_to_biome_rgb


def export_heightmap_png(game_y: np.ndarray, path: Path, *, bit16: bool = True) -> None:
    """Write heightmap.png for custom heightmap importers / RWG tools."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if bit16:
        arr = to_heightmap_png_array(game_y)
        # Pillow 12+: pass dtype array; mode kw is deprecated for type changes
        Image.fromarray(arr).save(path)
    else:
        # Clamp, never wrap: game_y from engine-height profiles can exceed 255
        # (Everest ≈ 8949) and a plain astype(uint8) would store 8949 % 256 = 69.
        y = np.clip(np.rint(np.asarray(game_y, dtype=np.float64)), 0, 255).astype(np.uint8)
        Image.fromarray(y).save(path)


def export_biome_png(landcover: np.ndarray, path: Path) -> None:
    """Write biomes.png style RGB map from landcover codes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = landcover_to_biome_rgb(landcover)
    Image.fromarray(rgb, mode="RGB").save(path)


def export_preview_png(
    elev_m: np.ndarray,
    landcover: np.ndarray,
    path: Path,
) -> None:
    """Hillshade + biome tint preview for humans (not used by the game)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    elev = np.asarray(elev_m, dtype=np.float64)
    # simple hillshade
    gy, gx = np.gradient(elev)
    slope = np.pi / 2 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azimuth = np.radians(315.0)
    altitude = np.radians(45.0)
    shaded = np.sin(altitude) * np.sin(slope) + np.cos(altitude) * np.cos(slope) * np.cos(
        azimuth - aspect
    )
    shaded = np.clip(shaded, 0, 1)

    biome = landcover_to_biome_rgb(landcover).astype(np.float64)
    # darken water slightly already blue
    lit = biome * (0.35 + 0.65 * shaded[..., None])
    img = np.clip(lit, 0, 255).astype(np.uint8)
    Image.fromarray(img, mode="RGB").save(path)


def export_region_pack(
    elev_m: np.ndarray,
    landcover: np.ndarray,
    out_dir: Path,
    *,
    sea_level_y: int = 32,
    name: str = "RealEarthRegion",
) -> dict:
    """Export a vanilla-friendly region folder: heightmap, biomes, preview, meta."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    game_y = compress_elevation(elev_m, sea_level_y=sea_level_y)
    export_heightmap_png(game_y, out_dir / "heightmap.png", bit16=True)
    export_heightmap_png(game_y, out_dir / "heightmap_8bit.png", bit16=False)
    export_biome_png(landcover, out_dir / "biomes.png")
    export_preview_png(elev_m, landcover, out_dir / "preview.png")

    meta = {
        "name": name,
        "width": int(elev_m.shape[1]),
        "height": int(elev_m.shape[0]),
        "sea_level_game_y": sea_level_y,
        "files": [
            "heightmap.png",
            "heightmap_8bit.png",
            "biomes.png",
            "preview.png",
        ],
        "install_hint": (
            "Use with a custom heightmap importer mod (e.g. Nexus 'Custom Height Map Importer') "
            "or your preferred RWG heightmap workflow for the current 7DTD version. "
            "Place heightmap.png as required by that mod; biomes.png may need palette remapping."
        ),
    }
    (out_dir / "export_meta.json").write_text(
        __import__("json").dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return meta
