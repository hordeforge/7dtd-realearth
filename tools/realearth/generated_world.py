"""Emit a complete 7DTD GeneratedWorlds folder for one continuous map.

DTM: little-endian uint16, height_u16 = game_y * 256 (verified on sample worlds).
Layout matches player GeneratedWorlds/* (dtm.raw, biomes, splats, map_info.xml, ...).

Version stamps must match the live client major or the game warns:
  "this world was created with a different major version..."
map_info GameVersion e.g. V.3.0.1; main.ttw e.g. V 3.0.1 (b4).
"""

from __future__ import annotations

import json
import re
import zlib
from pathlib import Path
from xml.sax.saxutils import escape as saxutils_escape

import numpy as np
from PIL import Image

from realearth import DEFAULT_SEA_LEVEL_GAME_Y, JsonDict
from realearth.bake_world import resize_arrays, snap_world_size
from realearth.density import (
    apply_urban_from_density,
    detect_city_cores,
    stamp_prefabs_from_density,
    write_cities_json,
    write_prefabs_xml,
)
from realearth.export_7dtd import export_preview_png
from realearth.height import compress_elevation
from realearth.landcover import LandCover
from realearth.settlements import (
    SEED_SETTLEMENTS,
    Settlement,
    edge_radius_m_from_properties,
)
from realearth.viewer_export import mosaic_pack

# Verified against this install's biomes.xml biomemapcolor
BIOME_RGB = {
    LandCover.OCEAN: (0, 64, 0),  # no separate water in map colors;
    # forest under water mask via height
    LandCover.INLAND_WATER: (0, 64, 0),
    LandCover.ICE: (255, 255, 255),
    LandCover.BARREN: (255, 168, 0),  # wasteland-ish
    LandCover.GRASS: (0, 64, 0),
    LandCover.SHRUB: (255, 228, 119),  # desert
    LandCover.FOREST: (0, 64, 0),
    LandCover.WETLAND: (0, 64, 0),
    LandCover.CROPLAND: (0, 64, 0),
    LandCover.URBAN: (255, 168, 0),  # wasteland (cities)
    LandCover.SNOW: (255, 255, 255),
    LandCover.DESERT: (255, 228, 119),
    LandCover.UNKNOWN: (0, 64, 0),
}

# More accurate: ocean should still paint forest terrain under water; height handles water.
# Burnt for sparse/barren mid
BIOME_RGB[LandCover.BARREN] = (186, 0, 255)  # burnt_forest #ba00ff


def landcover_to_vanilla_biome_rgb(lc: np.ndarray) -> np.ndarray:
    arr = np.asarray(lc, dtype=np.uint8)
    h, w = arr.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[:] = (0, 64, 0)  # default pine_forest
    for code, color in BIOME_RGB.items():
        mask = arr == int(code)
        if np.any(mask):
            rgb[mask] = color
    return rgb


def game_y_to_dtm_u16(game_y: np.ndarray) -> np.ndarray:
    """Convert game block heights (0-255) to dtm.raw uint16 (y * 256)."""
    y = np.asarray(game_y, dtype=np.float64)
    y = np.clip(y, 1, 250)
    return (y * 256.0).astype(np.uint16)


def write_dtm_raw(path: Path, elev_u16: np.ndarray) -> None:
    """Write row-major Z,X little-endian uint16 (verified zx indexing)."""
    arr = np.asarray(elev_u16, dtype="<u2")
    path.write_bytes(arr.tobytes(order="C"))


def crc32_file(path: Path) -> int:
    return zlib.crc32(path.read_bytes()) & 0xFFFFFFFF


def write_checksums(world_dir: Path, names: list[str]) -> None:
    lines = []
    for n in names:
        p = world_dir / n
        if p.exists():
            lines.append(f"{n}={crc32_file(p)}")
    # BOM-less is fine; sample had BOM
    (world_dir / "checksums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


# Fallback when client logs are missing (must match installed Steam major).
_DEFAULT_MAP_INFO_VERSION = "V.3.0.1"
_DEFAULT_TTW_VERSION = "V 3.0.1 (b4)"

_CLIENT_VERSION_RE = re.compile(
    r"Version:\s*(V\s+[\d.]+(?:\s*\(b\d+\))?)\s+Compatibility Version:\s*(V\s+[\d.]+)",
    re.IGNORECASE,
)


def detect_client_versions() -> tuple[str, str]:
    """Return (map_info GameVersion, main.ttw version) for the live client.

    Prefers the newest Proton/native output_log line:
      Version: V 3.0.1 (b4) Compatibility Version: V 3.0.1
    map_info uses dotted form V.3.0.1 (no space); main.ttw uses the full Version string.
    """
    log_roots = [
        Path.home()
        / ".local/share/Steam/steamapps/compatdata/251570/pfx/drive_c/users/steamuser"
        / "AppData/Roaming/7DaysToDie/logs",
        Path.home() / ".local/share/7DaysToDie",
    ]
    logs: list[Path] = []
    for root in log_roots:
        if root.is_dir():
            logs.extend(root.glob("output_log_client__*.txt"))
            logs.extend(root.glob("**/output_log*.txt"))
    logs = sorted(
        {p.resolve() for p in logs if p.is_file()}, key=lambda p: p.stat().st_mtime
    )
    for log in reversed(logs):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _CLIENT_VERSION_RE.search(text)
        if not m:
            continue
        ttw = m.group(1).strip()
        # Compatibility Version is "V 3.0.1" → map_info "V.3.0.1"
        compat = m.group(2).strip().replace("V ", "V.", 1).replace(" ", "")
        if not compat.startswith("V."):
            compat = "V." + compat.lstrip("Vv.")
        return compat, ttw
    return _DEFAULT_MAP_INFO_VERSION, _DEFAULT_TTW_VERSION


def detect_game_version_string() -> str:
    """map_info GameVersion (e.g. V.3.0.1) for the live Steam client."""
    return detect_client_versions()[0]


def detect_ttw_version_string() -> str:
    """main.ttw embedded version (e.g. V 3.0.1 (b4))."""
    return detect_client_versions()[1]


def write_ttw_with_version(
    path: Path, template: Path, version: str | None = None
) -> None:
    """Copy template main.ttw and rewrite embedded game version string."""
    version = version or detect_ttw_version_string()
    data = bytearray(template.read_bytes())
    if len(data) < 10 or data[:4] != b"ttw\0":
        path.write_bytes(template.read_bytes())
        return
    ver_bytes = version.encode("ascii")
    if len(ver_bytes) > 255:
        ver_bytes = ver_bytes[:255]
    old_len = data[8]
    # Replace version payload; splice if length changed
    head = bytes(data[:8]) + bytes([len(ver_bytes)]) + ver_bytes
    path.write_bytes(head + bytes(data[9 + old_len :]))


def write_map_info(
    path: Path, size: int, name: str, game_version: str | None = None
) -> None:
    # If present, GameVersion major must match the client or a warning is shown.
    gv = game_version or detect_game_version_string()
    # World names come from --name (arbitrary text). Escape for the attribute
    # context so '&', '<', '>' and quotes cannot break map_info.xml.
    safe_name = saxutils_escape(name, {'"': "&quot;"})
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<MapInfo>
  <property name="Scale" value="1" />
  <property name="HeightMapSize" value="{size},{size}" />
  <property name="Modes" value="Survival,SurvivalSP,SurvivalMP,Creative" />
  <property name="FixedWaterLevel" value="false" />
  <property name="RandomGeneratedWorld" value="false" />
  <property name="GameVersion" value="{gv}" />
  <property name="Description" value="RealEarth continuous single map: {safe_name}" />
</MapInfo>
"""
    path.write_text(xml, encoding="utf-8")


def write_spawnpoints(
    path: Path,
    size: int,
    game_y: np.ndarray,
    sea_level: int = DEFAULT_SEA_LEVEL_GAME_Y,
) -> None:
    """Spawn points in world-centered coords (origin at map center)."""
    h, w = game_y.shape
    half = size // 2
    # Sample a few land cells near center
    pts: list[tuple[int, float, int]] = []
    cy, cx = h // 2, w // 2
    for dy in range(-size // 4, size // 4, max(1, size // 16)):
        for dx in range(-size // 4, size // 4, max(1, size // 16)):
            y = cy + dy
            x = cx + dx
            if y < 0 or x < 0 or y >= h or x >= w:
                continue
            elev = int(game_y[y, x])
            if elev <= sea_level + 2:
                continue
            # world pos: image x,z → centered
            wx = x - half
            wz = y - half  # z increases south in image if north is top; match sample
            pts.append((wx, float(elev) + 1.5, wz))
            if len(pts) >= 12:
                break
        if len(pts) >= 12:
            break
    if not pts:
        pts = [(0, float(sea_level + 5), 0)]

    lines = ["<spawnpoints>"]
    for i, (wx, wy, wz) in enumerate(pts):
        rot = (i * 37) % 360
        lines.append(
            f'    <spawnpoint position="{wx},{wy:.5f},{wz}" rotation="0,{rot},0"/>'
        )
    lines.append("</spawnpoints>\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_radiation(path: Path, size: int) -> None:
    """Black interior, thin magenta radiation border (common RWG style)."""
    img = np.zeros((size, size, 4), dtype=np.uint8)
    border = max(8, size // 64)
    # radiation rim
    img[:border, :] = (255, 0, 255, 255)
    img[-border:, :] = (255, 0, 255, 255)
    img[:, :border] = (255, 0, 255, 255)
    img[:, -border:] = (255, 0, 255, 255)
    Image.fromarray(img, mode="RGBA").save(path)


def write_splats(path3: Path, path4: Path, size: int, lc: np.ndarray) -> None:
    """Simple splat maps: mostly empty with slight biome tint."""
    # splat3 often encodes dirt/stone/ore weights in RGBA channels
    s3 = np.zeros((size, size, 4), dtype=np.uint8)
    s4 = np.zeros((size, size, 4), dtype=np.uint8)
    # leave mostly zero (default terrain look); slight variation
    rng = np.random.default_rng(42)
    noise = rng.integers(0, 20, size=(size, size), dtype=np.uint8)
    s3[:, :, 0] = noise
    Image.fromarray(s3, mode="RGBA").save(path3)
    Image.fromarray(s4, mode="RGBA").save(path4)
    # half res
    half = size // 2
    Image.fromarray(s3, mode="RGBA").resize(
        (half, half), Image.Resampling.BILINEAR
    ).save(path3.with_name("splat3_half.png"))
    Image.fromarray(s4, mode="RGBA").resize(
        (half, half), Image.Resampling.BILINEAR
    ).save(path4.with_name("splat4_half.png"))
    # processed = same as full for our purposes
    Image.fromarray(s3, mode="RGBA").save(path3.with_name("splat3_processed.png"))
    Image.fromarray(s4, mode="RGBA").save(path4.with_name("splat4_processed.png"))


def _find_ttw_template() -> Path | None:
    """Prefer a main.ttw from the current game install (Pregen), then any GeneratedWorlds."""
    home = Path.home()
    preferred = [
        home
        / ".local/share/Steam/steamapps/common/7 Days To Die/Data/Worlds/Pregen06k01/main.ttw",
        home
        / ".local/share/Steam/steamapps/common/7 Days to Die Dedicated Server"
        / "Data/Worlds/Pregen06k01/main.ttw",
    ]
    for p in preferred:
        if p.exists():
            return p
    sample = home / ".local/share/7DaysToDie/GeneratedWorlds"
    if sample.is_dir():
        for p in sample.glob("*/main.ttw"):
            return p
    return None


def write_main_ttw(
    path: Path,
    template: Path | None = None,
    *,
    version: str | None = None,
) -> None:
    """Copy a known-good main.ttw and stamp current game version (avoids major-version warning)."""
    tmpl = template if template and template.exists() else _find_ttw_template()
    if tmpl is None:
        raise FileNotFoundError(
            "main.ttw template required: install 7DTD (Pregen worlds) or pass --ttw-template"
        )
    write_ttw_with_version(path, tmpl, version=version or detect_ttw_version_string())


def write_water_info(path: Path) -> None:
    path.write_text("<WaterSources>\n</WaterSources>\n", encoding="utf-8")


def bake_generated_world(
    pack_dir: Path,
    out_dir: Path,
    *,
    size: int = 4096,
    name: str = "RealEarth",
    sea_level_y: int = DEFAULT_SEA_LEVEL_GAME_Y,
    ttw_template: Path | None = None,
    game_version: str | None = None,
) -> JsonDict:
    """Build a full GeneratedWorlds-compatible continuous map from a tile pack.

    Cities: density channel + city cores → vanilla POI stamps in prefabs.xml
    (dense where population/built-up is high).
    """
    size = snap_world_size(size)
    pack_dir = Path(pack_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = mosaic_pack(pack_dir)
    elev = data.elevation
    lc = data.landcover
    pop = data.population
    man = data.manifest
    bbox = man.bbox or {"west": -180, "south": -90, "east": 180, "north": 90}

    # Resize to world size
    elev_r, lc_r, pop_r = resize_arrays(elev, lc, pop, size)

    # Urban biome from density
    lc_r = apply_urban_from_density(lc_r, pop_r, urban_threshold=90)

    # 1:1 m→block into stock DTM (peaks above 250 clamp in file format only, not a curve)

    game_y = compress_elevation(
        elev_r,
        sea_level_y=sea_level_y,
        max_y=250,  # dtm.raw uint16 packing only holds stock-range Y
        profile="one_to_one",
        regional_exaggeration=1.0,
    )
    ocean = lc_r == int(LandCover.OCEAN)
    game_y = np.asarray(game_y, dtype=np.int32).copy()
    game_y[ocean] = np.minimum(game_y[ocean], sea_level_y)
    game_y = np.clip(game_y, 1, 250).astype(np.uint8)

    dtm = game_y_to_dtm_u16(game_y)
    write_dtm_raw(out_dir / "dtm.raw", dtm)
    write_dtm_raw(out_dir / "dtm_processed.raw", dtm)

    biome_rgb = landcover_to_vanilla_biome_rgb(lc_r)
    Image.fromarray(biome_rgb, mode="RGB").save(out_dir / "biomes.png")
    Image.fromarray(pop_r, mode="L").save(out_dir / "population.png")

    # City cores from density peaks + named settlements
    # Exact inverse of settlements.population_to_byte (50*log10(p+1)): the byte
    # channel is log-encoded, so a linear scale misreads mid-density towns as
    # large cities when detect_city_cores re-bands them.
    dens_float = np.float64(10.0) ** (pop_r.astype(np.float64) / 50.0) - 1.0
    settles = list(SEED_SETTLEMENTS)
    spath = pack_dir / "settlements.json"
    if spath.exists():
        raw = json.loads(spath.read_text(encoding="utf-8"))
        settles = []
        for s in raw:
            lon = float(s["lon"])
            lat = float(s["lat"])
            edge = edge_radius_m_from_properties(s, lon, lat)
            settles.append(
                Settlement(
                    name=s["name"],
                    lon=lon,
                    lat=lat,
                    population=int(s.get("population") or 0),
                    edge_radius_m=edge,
                )
            )
    cores = detect_city_cores(
        dens_float,
        bbox["west"],
        bbox["south"],
        bbox["east"],
        bbox["north"],
        settlements=settles,
        min_peak=40.0,
        min_separation_px=max(12, size // 64),
    )
    stamps = stamp_prefabs_from_density(
        pop_r, game_y, world_size=size, sea_level=sea_level_y, cores=cores
    )
    write_prefabs_xml(out_dir / "prefabs.xml", stamps)
    write_cities_json(out_dir / "cities.json", cores, stamps)

    write_radiation(out_dir / "radiation.png", size)
    write_splats(out_dir / "splat3.png", out_dir / "splat4.png", size, lc_r)
    # 3.x worlds also ship splat1/2 + water_info (empty OK)
    Image.fromarray(np.zeros((size, size, 4), dtype=np.uint8), mode="RGBA").save(
        out_dir / "splat1.png"
    )
    Image.fromarray(np.zeros((size, size, 4), dtype=np.uint8), mode="RGBA").save(
        out_dir / "splat2.png"
    )
    write_water_info(out_dir / "water_info.xml")
    map_ver, ttw_ver = detect_client_versions()
    if game_version:
        map_ver = game_version
        # Dotted map_info form only ("V.3.0.1"): keep the live client ttw stamp,
        # which carries the full "V x.y.z (bN)" string the major check wants.
        if not (game_version.startswith("V.") and " " not in game_version):
            ttw_ver = game_version
    write_map_info(out_dir / "map_info.xml", size, name, game_version=map_ver)
    write_spawnpoints(out_dir / "spawnpoints.xml", size, game_y, sea_level=sea_level_y)
    # main.ttw embeds full client Version string, e.g. "V 3.0.1 (b4)"
    write_main_ttw(out_dir / "main.ttw", ttw_template, version=ttw_ver)

    export_preview_png(elev_r, lc_r, out_dir / "preview.png")

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

    meta = {
        "name": name,
        "size": size,
        "dtm_bytes": size * size * 2,
        "sea_level_game_y": sea_level_y,
        "map_mode": "Baked",
        "single_world": True,
        "city_cores": len(cores),
        "prefab_stamps": len(stamps),
        "files": required + ["cities.json", "population.png"],
    }
    world_json = out_dir / "realearth_world.json"
    world_json.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return meta
