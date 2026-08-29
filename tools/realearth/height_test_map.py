"""Build height-mod test maps.

Modes:
  * Everest DEM (default): real Terrarium meters, 1:1 gameY ≈ 8949
  * Staged peak (`peak_game_y=500`): synthetic cone with peak at that game Y

Outputs (Everest):
  data/samples/height_test/: .rte pack
  worlds/RealEarth_HeightTest/: baked world (DTM clamps ~250)

Outputs (staged, e.g. 500):
  data/samples/height_test_500/
  worlds/RealEarth_H500/
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from realearth import (
    ENGINE_TARGET_MAX_Y,
    EVEREST_METERS_ASL,
    FLY_OVER_HEADROOM_M,
    JsonDict,
)
from realearth.elevation import fetch_region_open_meteo, fetch_region_terrarium
from realearth.generated_world import (
    bake_generated_world,
    game_y_to_dtm_u16,
    write_checksums,
    write_dtm_raw,
)
from realearth.height import compress_elevation
from realearth.landcover import LandCover
from realearth.tile_format import (
    EarthTile,
    Manifest,
    tile_path,
    write_manifest,
    write_tile,
)
from realearth.viewer_export import mosaic_pack

# Local pack size (single .rte tile)
TILE = 512

# Test fixtures keep the historical low anchor (sea=32) so staged peak_game_y
# stays a small absolute game Y (peak 500 → elev 468) and the Everest fixture
# keeps its ~8778 peak. The product DEFAULT_SEA_LEVEL_GAME_Y (16000) is for
# real-Earth packs that must represent trenches below sea.
TEST_SEA_LEVEL_GAME_Y = 32

# Mount Everest summit ≈ 86.925°E, 27.988°N, small Himalaya footprint
EVEREST_BBOX = {
    "west": 86.80,
    "south": 27.88,
    "east": 87.05,
    "north": 28.12,
}
# Peak marker (WGS84)
EVEREST_LON = 86.9250
EVEREST_LAT = 27.9881

# Neutral bbox for synthetic staged maps (not real geography)
STAGED_BBOX = {
    "west": 0.0,
    "south": 0.0,
    "east": 0.05,
    "north": 0.05,
}
STAGED_LON = 0.025
STAGED_LAT = 0.025


def cone_elevation(
    size: int = TILE,
    *,
    peak_elev_m: float,
    plains_elev_m: float = 40.0,
) -> np.ndarray:
    """Centered cone: plains → peak (meters ASL)."""
    yy, xx = np.mgrid[0:size, 0:size]
    cy = cz = size // 2
    r = np.sqrt((xx - cy) ** 2 + (yy - cz) ** 2) / (size * 0.48)
    t = np.clip(1.0 - r, 0.0, 1.0)
    elev = plains_elev_m + (peak_elev_m - plains_elev_m) * np.power(t, 1.35)
    return elev.astype(np.float32)


def everest_cone_elevation(size: int = TILE) -> np.ndarray:
    """Synthetic fallback if network DEM fetch fails."""
    return cone_elevation(size, peak_elev_m=float(EVEREST_METERS_ASL), plains_elev_m=200.0)


def staged_peak_elevation(size: int = TILE, *, peak_game_y: int = 500) -> np.ndarray:
    """Cone whose 1:1 peak is exactly peak_game_y (elev_m = peak_game_y - sea)."""
    sea = TEST_SEA_LEVEL_GAME_Y
    peak_elev = max(1.0, float(peak_game_y - sea))
    plains_elev = min(40.0, peak_elev * 0.1)
    return cone_elevation(size, peak_elev_m=peak_elev, plains_elev_m=plains_elev)


def fetch_everest_elevation(
    size: int = TILE,
    *,
    source: str = "terrarium",
    terrarium_zoom: int = 11,
) -> tuple[np.ndarray, list[str]]:
    """Download real DEM for the Everest bbox → size×size float32 meters ASL.

    source: terrarium (AWS open tiles) | open_meteo | synthetic
    """
    b = EVEREST_BBOX
    west, south, east, north = b["west"], b["south"], b["east"], b["north"]
    sources: list[str] = []

    if source == "synthetic":
        return everest_cone_elevation(size), ["synthetic Everest cone (offline fallback)"]

    try:
        if source == "open_meteo":
            elev = fetch_region_open_meteo(west, south, east, north, size, size)
            sources = [
                "Open-Meteo Elevation API (open data, not Google)",
                f"bbox={west},{south},{east},{north}",
            ]
        else:
            elev = fetch_region_terrarium(west, south, east, north, size, size, zoom=terrarium_zoom)
            sources = [
                "AWS Terrain Tiles / Mapzen Terrarium (open data, not Google Earth)",
                f"zoom={terrarium_zoom} bbox={west},{south},{east},{north}",
            ]
        elev = np.asarray(elev, dtype=np.float32)
        if elev.shape != (size, size):
            elev = np.asarray(
                Image.fromarray(elev, mode="F").resize((size, size), Image.Resampling.BILINEAR),
                dtype=np.float32,
            )
        # NaN fill from neighbors / synthetic
        if np.isnan(elev).any():
            fill = float(np.nanmedian(elev)) if np.isfinite(elev).any() else 4000.0
            elev = np.where(np.isfinite(elev), elev, fill).astype(np.float32)
        return elev, sources
    except Exception as ex:
        # Loud, not silent: a network outage must never quietly substitute a
        # synthetic cone for the real DEM the operator asked for. The manifest
        # records the fallback, but stderr is what a human actually sees.
        import sys

        print(
            f"WARNING: DEM fetch failed ({source}): {ex}",
            file=sys.stderr,
        )
        print(
            "WARNING: falling back to SYNTHETIC Everest cone; the pack will not "
            "contain real geography. Re-run with working network or --source geotiff.",
            file=sys.stderr,
        )
        sources = [
            f"DEM fetch failed ({source}): {ex}",
            "fallback: synthetic Everest cone",
        ]
        return everest_cone_elevation(size), sources


def landcover_from_elev(elev: np.ndarray) -> np.ndarray:
    """Heuristic landcover from elevation (works for Himalaya and staged cones)."""
    lc = np.full(elev.shape, int(LandCover.GRASS), dtype=np.uint8)
    peak = float(np.nanmax(elev)) if elev.size else 0.0
    # Relative bands so a 400 m staged peak (sea 100) still gets variety
    t1, t2, t3, t4 = peak * 0.25, peak * 0.5, peak * 0.75, peak * 0.9
    lc[elev <= 0] = int(LandCover.OCEAN)
    lc[(elev > 0) & (elev < t1)] = int(LandCover.FOREST)
    lc[(elev >= t1) & (elev < t2)] = int(LandCover.GRASS)
    lc[(elev >= t2) & (elev < t3)] = int(LandCover.BARREN)
    lc[(elev >= t3) & (elev < t4)] = int(LandCover.SNOW)
    lc[elev >= t4] = int(LandCover.ICE)
    return lc


def peak_pixel(elev: np.ndarray) -> tuple[int, int]:
    """Return (x, z) of maximum elevation (z = row)."""
    z, x = np.unravel_index(int(np.argmax(elev)), elev.shape)
    return int(x), int(z)


def build_height_test_pack(
    out_dir: Path,
    *,
    source: str = "terrarium",
    terrarium_zoom: int = 11,
    size: int = TILE,
    peak_game_y: int | None = None,
    name: str | None = None,
) -> JsonDict:
    """Write .rte pack from real Everest DEM, synthetic Everest, or staged peak_game_y."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # A staged run is driven entirely by a positive peak_game_y; binding it once
    # keeps the staged branch free of re-narrowing.
    pg = peak_game_y if peak_game_y is not None and peak_game_y > 0 else None
    staged = pg is not None
    if pg is not None:
        elev = staged_peak_elevation(size, peak_game_y=pg)
        sources = [
            f"synthetic staged cone peak_game_y={pg}",
            f"elev_m peak = {pg - TEST_SEA_LEVEL_GAME_Y} (1:1 sea={TEST_SEA_LEVEL_GAME_Y})",
        ]
        world_name = name or f"RealEarth_H{pg}"
        region = f"Staged height test (peak gameY={pg})"
        bbox = dict(STAGED_BBOX)
        summit_lon, summit_lat = STAGED_LON, STAGED_LAT
        engine_max = pg  # content ceiling matches peak for the test
        notes = (
            f"Staged height-mod test. Peak elev≈{float(elev.max()):.0f} m ASL → "
            f"1:1 gameY≈{TEST_SEA_LEVEL_GAME_Y + int(round(float(elev.max())))}. "
            f"EngineMaxGameY={engine_max}. Full solid fill (no Everest-scale cost)."
        )
    else:
        elev, sources = fetch_everest_elevation(size, source=source, terrarium_zoom=terrarium_zoom)
        world_name = name or "RealEarth_HeightTest"
        region = "Mount Everest / Khumbu (Himalaya)"
        bbox = dict(EVEREST_BBOX)
        summit_lon, summit_lat = EVEREST_LON, EVEREST_LAT
        engine_max = ENGINE_TARGET_MAX_Y
        notes = None  # filled below after peak calc

    lc = landcover_from_elev(elev)
    pop = np.zeros_like(lc)

    tile_size = size
    tile = EarthTile(0, 0, elev, landcover=lc, population=pop)
    write_tile(tile_path(out_dir, 0, 0), tile)

    peak_m = float(elev.max())
    px, pz = peak_pixel(elev)
    peak_game_1to1 = TEST_SEA_LEVEL_GAME_Y + int(round(peak_m))
    if notes is None:
        notes = (
            f"Real Everest DEM test. Peak elev≈{peak_m:.0f} m ASL at pixel ({px},{pz}). "
            f"1:1 height mod → gameY≈{peak_game_1to1}. "
            f"Ceiling={ENGINE_TARGET_MAX_Y} (Everest + {FLY_OVER_HEADROOM_M} m fly room). "
            "No height compression."
        )

    man = Manifest(
        name=world_name,
        version=1,
        tile_size=tile_size,
        world_width=size,
        world_height=size,
        sea_level_game_y=TEST_SEA_LEVEL_GAME_Y,
        meters_per_block=1.0,
        bbox=bbox,
        tiles=[{"tx": 0, "tz": 0}],
        sources=sources,
        notes=notes,
    )
    write_manifest(out_dir / "earth.manifest.json", man)

    meta = {
        "name": world_name,
        "region": region,
        "summit_lon": summit_lon,
        "summit_lat": summit_lat,
        "peak_elev_m": peak_m,
        "peak_pixel_xz": [px, pz],
        "expected_everest_m": None if staged else EVEREST_METERS_ASL,
        "sea_level_game_y": TEST_SEA_LEVEL_GAME_Y,
        "engine_max_game_y": engine_max,
        "peak_game_y_one_to_one": peak_game_1to1,
        "target_peak_game_y": pg if pg is not None else peak_game_1to1,
        "staged": staged,
        "fly_headroom_m": 0 if staged else FLY_OVER_HEADROOM_M,
        "blocks_above_peak": max(0, engine_max - peak_game_1to1),
        "tile_size": tile_size,
        "world_size": size,
        "bbox": bbox,
        "sources": sources,
        "no_compression": True,
        "how_to_play": {
            "engine": "make engine-expand  # YDim=16384",
            "install": ("make install-height-500" if pg == 500 else "make install-height"),
            "streamed": "MapMode=Streamed + Data/tiles (this pack), host ~512",
            "baked": f"New Game → {world_name} (DTM 1:1 clamped ~250 at peak)",
            "teleport_hint": f"Peak in pack at local xz≈({px},{pz})",
            "reheight": (f"F1 → reheight  # expect gameY≈{peak_game_1to1} (elev_m≈{peak_m:.0f})"),
        },
    }
    (out_dir / "height_test.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    game_stock = compress_elevation(
        elev, sea_level_y=TEST_SEA_LEVEL_GAME_Y, max_y=250, profile="one_to_one"
    )
    game_mod = compress_elevation(
        elev,
        sea_level_y=TEST_SEA_LEVEL_GAME_Y,
        max_y=engine_max,
        profile="one_to_one",
        regional_exaggeration=1.0,
    )

    def _norm(a: np.ndarray) -> np.ndarray:
        a = a.astype(np.float64)
        return np.clip((a - a.min()) / max(1e-6, a.max() - a.min()) * 255, 0, 255).astype(np.uint8)

    Image.fromarray(_norm(elev), mode="L").save(out_dir / "preview_elev_m.png")
    Image.fromarray(np.clip(np.asarray(game_stock), 0, 255).astype(np.uint8), mode="L").save(
        out_dir / "preview_game_y_stock.png"
    )
    Image.fromarray(_norm(game_mod.astype(np.float64)), mode="L").save(
        out_dir / "preview_game_y_heightmod.png"
    )

    return {
        "pack_dir": str(out_dir),
        "peak_elev_m": peak_m,
        "peak_pixel": [px, pz],
        "peak_game_y_one_to_one": peak_game_1to1,
        "peak_game_y_stock_1to1_clamped": int(np.max(game_stock)),
        "sources": sources,
        "meta": meta,
    }


def bake_height_test_world(
    pack_dir: Path,
    out_dir: Path,
    *,
    size: int = 2048,
    name: str | None = None,
) -> JsonDict:
    """Bake playable GeneratedWorld; DTM is 1:1 into stock range (peak clamps ~250)."""
    pack_dir = Path(pack_dir)
    out_dir = Path(out_dir)

    if name is None:
        ht = pack_dir / "height_test.json"
        if ht.is_file():
            name = json.loads(ht.read_text(encoding="utf-8")).get("name") or "RealEarth_HeightTest"
        else:
            name = "RealEarth_HeightTest"

    meta = bake_generated_world(
        pack_dir,
        out_dir,
        size=size,
        name=name,
        sea_level_y=TEST_SEA_LEVEL_GAME_Y,
    )

    data = mosaic_pack(pack_dir)
    elev = data.elevation
    elev_i = Image.fromarray(np.asarray(elev, dtype=np.float32), mode="F")
    elev_r = np.asarray(elev_i.resize((size, size), Image.Resampling.BILINEAR), dtype=np.float32)
    game_y = compress_elevation(
        elev_r,
        sea_level_y=TEST_SEA_LEVEL_GAME_Y,
        max_y=250,
        profile="one_to_one",
        regional_exaggeration=1.0,
    )
    game_y = np.asarray(game_y, dtype=np.int32).copy()
    game_y[elev_r <= 0] = np.minimum(game_y[elev_r <= 0], TEST_SEA_LEVEL_GAME_Y)
    game_y = np.clip(game_y, 1, 250).astype(np.uint8)

    dtm = game_y_to_dtm_u16(game_y)
    write_dtm_raw(out_dir / "dtm.raw", dtm)
    write_dtm_raw(out_dir / "dtm_processed.raw", dtm)

    required = [
        "biomes.png",
        "dtm.raw",
        "dtm_processed.raw",
        "main.ttw",
        "map_info.xml",
        "prefabs.xml",
        "radiation.png",
        "spawnpoints.xml",
        "splat3.png",
        "splat3_half.png",
        "splat3_processed.png",
        "splat4.png",
        "splat4_half.png",
        "splat4_processed.png",
    ]
    write_checksums(out_dir, required)

    # Spawn near peak but slightly off-summit (safer), and at mid elevations
    half = size // 2
    pz, px = np.unravel_index(int(np.argmax(elev_r)), elev_r.shape)
    # scale pack peak pixel to world size
    pack_h, pack_w = elev.shape
    wx = int(px * size / pack_w) - half
    wz = int(pz * size / pack_h) - half
    peak_gy = int(
        game_y[
            pz * size // pack_h if False else min(size - 1, int(pz * size / pack_h)),
            min(size - 1, int(px * size / pack_w)),
        ]
    )
    # fix indices properly
    iz = min(size - 1, int(pz * size / pack_h))
    ix = min(size - 1, int(px * size / pack_w))
    peak_gy = int(game_y[iz, ix])
    wx = ix - half
    wz = iz - half

    # Base camp-ish: offset toward lower elevation
    ox, oz = wx - size // 16, wz + size // 20
    oix = int(np.clip(ox + half, 0, size - 1))
    oiz = int(np.clip(oz + half, 0, size - 1))
    base_gy = int(game_y[oiz, oix])

    spawns = [
        (ox, float(base_gy + 3), oz),
        (wx, float(min(peak_gy + 2, 248)), wz),
        (0, float(TEST_SEA_LEVEL_GAME_Y + 10), 0),
    ]
    lines = ["<spawnpoints>"]
    for i, (sx, sy, sz) in enumerate(spawns):
        lines.append(f'    <spawnpoint position="{sx},{sy:.5f},{sz}" rotation="0,{i * 45},0"/>')
    lines.append("</spawnpoints>\n")
    (out_dir / "spawnpoints.xml").write_text("\n".join(lines), encoding="utf-8")

    src_meta = pack_dir / "height_test.json"
    if src_meta.is_file():
        (out_dir / "height_test.json").write_text(src_meta.read_text(encoding="utf-8"))

    meta["stock_peak_game_y"] = peak_gy
    meta["peak_world_xz"] = [wx, wz]
    meta["size"] = size
    meta["height_test"] = True
    meta["real_dem"] = True
    (out_dir / "bake_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return meta


def build_all(
    repo_root: Path | None = None,
    *,
    world_size: int = 2048,
    source: str = "terrarium",
    terrarium_zoom: int = 11,
    pack_size: int = TILE,
    peak_game_y: int | None = None,
) -> JsonDict:
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    pg = peak_game_y if peak_game_y is not None and peak_game_y > 0 else None
    staged = pg is not None
    if pg is not None:
        pack = root / "data" / "samples" / f"height_test_{pg}"
        world = root / "worlds" / f"RealEarth_H{pg}"
        world_name = f"RealEarth_H{pg}"
    else:
        pack = root / "data" / "samples" / "height_test"
        world = root / "worlds" / "RealEarth_HeightTest"
        world_name = "RealEarth_HeightTest"

    pack_info = build_height_test_pack(
        pack,
        source=source if not staged else "synthetic",
        terrarium_zoom=terrarium_zoom,
        size=pack_size,
        peak_game_y=peak_game_y,
        name=world_name,
    )
    bake_info = bake_height_test_world(pack, world, size=world_size, name=world_name)
    return {
        "pack": pack_info,
        "world": bake_info,
        "pack_dir": str(pack),
        "world_dir": str(world),
        "world_name": world_name,
        "peak_game_y": pack_info.get("peak_game_y_one_to_one"),
        "engine_max_game_y": pack_info.get("meta", {}).get("engine_max_game_y"),
    }
