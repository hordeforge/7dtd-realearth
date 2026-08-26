"""Bake a continuous single-map world export for in-game use (one heightmap + biomes).

Output is one finite world (size 2048–16384) suitable for custom heightmap importers
or GeneratedWorlds-style folders. This is MapMode=Baked: fully usable as one large map.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from realearth import DEFAULT_SEA_LEVEL_GAME_Y, JsonDict
from realearth.export_7dtd import (
    export_biome_png,
    export_heightmap_png,
    export_preview_png,
)
from realearth.height import compress_elevation
from realearth.tile_format import Manifest, write_manifest
from realearth.viewer_export import mosaic_pack


def snap_world_size(size: int) -> int:
    """Clamp/round to a valid world size: multiple of 2048, 2048..16384."""
    size = int(size)
    if size < 2048:
        return 2048
    if size > 16384:
        return 16384
    # round to nearest multiple of 2048
    return max(2048, min(16384, int(round(size / 2048.0) * 2048)))


def resize_arrays(
    elev: np.ndarray,
    lc: np.ndarray,
    pop: np.ndarray | None,
    size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Resize mosaics to square `size` x `size` for a single continuous world."""
    elev_i = Image.fromarray(np.asarray(elev, dtype=np.float32), mode="F")
    elev_r = np.asarray(elev_i.resize((size, size), Image.Resampling.BILINEAR), dtype=np.float32)
    lc_r = np.asarray(
        Image.fromarray(np.asarray(lc, dtype=np.uint8), mode="L").resize(
            (size, size), Image.Resampling.NEAREST
        ),
        dtype=np.uint8,
    )
    if pop is not None:
        pop_r = np.asarray(
            Image.fromarray(np.asarray(pop, dtype=np.uint8), mode="L").resize(
                (size, size), Image.Resampling.BILINEAR
            ),
            dtype=np.uint8,
        )
    else:
        pop_r = np.zeros((size, size), dtype=np.uint8)
    return elev_r, lc_r, pop_r


def bake_world_from_pack(
    pack_dir: Path,
    out_dir: Path,
    *,
    size: int = 8192,
    name: str | None = None,
    sea_level_y: int = DEFAULT_SEA_LEVEL_GAME_Y,
) -> JsonDict:
    """Stitch pack tiles and bake one continuous world of `size`×`size` blocks."""
    size = snap_world_size(size)
    pack_dir = Path(pack_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = mosaic_pack(pack_dir)
    elev = data.elevation
    lc = data.landcover
    pop = data.population
    man = data.manifest
    world_name = name or man.name or "RealEarth"

    elev_r, lc_r, pop_r = resize_arrays(elev, lc, pop, size)
    game_y = compress_elevation(elev_r, sea_level_y=sea_level_y)

    export_dir = out_dir / "export_7dtd"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_heightmap_png(game_y, export_dir / "heightmap.png", bit16=True)
    export_heightmap_png(game_y, export_dir / "heightmap_8bit.png", bit16=False)
    export_biome_png(lc_r, export_dir / "biomes.png")
    export_preview_png(elev_r, lc_r, export_dir / "preview.png")

    # Also write at world root for importers that look next to map_info
    export_heightmap_png(game_y, out_dir / "heightmap.png", bit16=True)
    export_biome_png(lc_r, out_dir / "biomes.png")
    export_preview_png(elev_r, lc_r, out_dir / "preview.png")

    # Population as greyscale helper (not vanilla, for our tools / future stamps)
    Image.fromarray(pop_r, mode="L").save(out_dir / "population.png")

    # Settlements remapped into world pixel space
    settlements = []
    src_set = pack_dir / "settlements.json"
    bbox = man.bbox
    if src_set.exists() and bbox:
        west, south, east, north = (
            bbox["west"],
            bbox["south"],
            bbox["east"],
            bbox["north"],
        )
        for s in json.loads(src_set.read_text(encoding="utf-8")):
            lon, lat = float(s["lon"]), float(s["lat"])
            if not (west <= lon <= east and south <= lat <= north):
                continue
            u = (lon - west) / max(1e-9, east - west)
            v = (north - lat) / max(1e-9, north - south)
            settlements.append(
                {
                    **s,
                    "world_x": int(u * (size - 1)),
                    "world_z": int(v * (size - 1)),
                }
            )
    (out_dir / "settlements.json").write_text(
        json.dumps(settlements, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Prefab stamp plan (consumed by Streamed/Baked runtime when hooked)
    prefabs = {
        "world_name": world_name,
        "size": size,
        "pois": [
            {
                "name": s.get("name"),
                "band": s.get("band"),
                "x": s.get("world_x"),
                "z": s.get("world_z"),
                "population": s.get("population"),
            }
            for s in settlements
        ],
    }
    (out_dir / "prefab_plan.json").write_text(
        json.dumps(prefabs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # map_info-style metadata for operators
    map_info = {
        "Name": world_name,
        "Scale": 1,
        "HeightMapSize": size,
        "Modes": "Survival",
        "Description": (
            f"RealEarth baked continuous map {size}x{size}. "
            f"One playable world. Sources: {', '.join(man.sources[:4])}"
        ),
        "RealEarth": {
            "MapMode": "Baked",
            "size": size,
            "bbox": bbox,
            "meters_per_block_source": man.meters_per_block,
            "sea_level_game_y": sea_level_y,
            "install": [
                "Install a custom heightmap importer mod for 7DTD 3.0.1, OR",
                "Use your preferred RWG/custom heightmap workflow with heightmap.png + biomes.png",
                "Place files as that tool expects (often heightmap.png next to its config)",
                "Start a NEW game on this world: one continuous map, one save",
            ],
        },
    }
    (out_dir / "map_info.json").write_text(
        json.dumps(map_info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "README_INSTALL.txt").write_text(
        "\n".join(
            [
                f"RealEarth baked world: {world_name}",
                f"Size: {size} x {size} blocks (one continuous map)",
                "",
                "This is a SINGLE in-game world, not multiple region saves.",
                "",
                "Files:",
                "  heightmap.png   16-bit terrain for custom heightmap importers",
                "  biomes.png      landcover/biome paint",
                "  preview.png     human preview",
                "  population.png  density helper",
                "  settlements.json / prefab_plan.json",
                "  export_7dtd/    duplicate export bundle",
                "",
                "Install:",
                "  1. Put a heightmap importer mod in Mods/ (3.0.1 compatible)",
                "  2. Point it at heightmap.png (and biomes if supported)",
                "  3. Generate / start one new game world",
                "  4. Play edge-to-edge on this one map",
                "",
                "For full-Earth travel beyond 16k, use MapMode=Streamed with the C# mod.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    # Lightweight manifest for tools
    baked = Manifest(
        name=world_name,
        tile_size=size,
        world_width=size,
        world_height=size,
        meters_per_block=man.meters_per_block,
        bbox=bbox,
        tiles=[{"tx": 0, "tz": 0}],
        sources=list(man.sources) + ["baked continuous single-map export"],
        notes=f"Baked single world {size}x{size} for in-game use as one map.",
        sea_level_game_y=sea_level_y,
    )
    write_manifest(out_dir / "earth.manifest.json", baked)

    return {
        "name": world_name,
        "size": size,
        "out_dir": str(out_dir.resolve()),
        "heightmap": str(out_dir / "heightmap.png"),
        "biomes": str(out_dir / "biomes.png"),
        "settlements": len(settlements),
    }


def planet_scale_for_size(size: int) -> float:
    """Meters per block so full Earth equator fits in `size` blocks."""
    return 40_075_017 / float(size)
