"""Population + built-up density → city cores and prefab placement plans.

Open data (not Google):
  - Point settlements (Natural Earth / GeoNames / seed list)
  - Optional GeoTIFF: people/km² (WorldPop/GHSL-POP) or built-up fraction (GHS-BUILT)

Output bands drive landcover URBAN paint and 7DTD prefabs.xml decorations.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from realearth.elevation import grid_lonlat
from realearth.landcover import LandCover
from realearth.settlements import (
    Settlement,
    paint_settlement_density,
    population_to_byte,
    urban_radius_m_from_population,
)

# Vanilla POI names present on this install (V2.x Prefabs/POIs)
PREFAB_POOLS: dict[str, list[str]] = {
    "metro": [
        "downtown_building_04",
        "downtown_strip_06",
        "downtown_strip_08",
        "downtown_filler_08",
        "downtown_filler_14",
        "downtown_filler_plaza_01",
        "departure_city_blk_01",
        "diersville_city_blk_01",
        "commercial_strip_08",
        "commercial_site_01",
        "gas_station_05",
        "house_modern_15",
        "house_modern_20",
    ],
    "large_city": [
        "downtown_strip_06",
        "downtown_filler_08",
        "commercial_strip_09",
        "commercial_site_02",
        "gas_station_03",
        "house_modern_10",
        "house_modern_12",
        "house_old_mansard_03",
        "house_old_victorian_02",
    ],
    "town": [
        "commercial_strip_10",
        "gas_station_01",
        "house_modern_05",
        "house_modern_06",
        "house_old_bungalow_02",
        "house_old_ranch_01",
        "church_01",
        "house_old_cottage_01",
    ],
    "village": [
        "gas_station_01",
        "house_country_01",
        "house_old_bungalow_05",
        "house_old_ranch_03",
        "cabin_01",
        "farm_11",
        "church_01",
    ],
    "hamlet": [
        "cabin_02",
        "cabin_05",
        "house_old_cottage_01",
        "farm_12",
        "barn_01",
        "abandoned_house_01",
    ],
    "rural_scatter": [
        "cabin_06",
        "farm_19",
        "abandoned_house_03",
        "bus_stop_01",
    ],
}

# Spacing in blocks between prefab stamps by density band
SPACING_BLOCKS: dict[str, int] = {
    "metro": 48,
    "large_city": 64,
    "town": 90,
    "village": 120,
    "hamlet": 160,
    "rural_scatter": 220,
}


@dataclass(frozen=True, slots=True)
class CityCore:
    name: str
    lon: float
    lat: float
    population: int
    band: str
    peak_density: float  # people/km² or synthetic equivalent
    built_up: float  # 0-1 estimated built fraction
    local_x: int  # image / sample coords
    local_z: int
    # Urban edge half-width in meters from density/built-up map (connected component).
    edge_radius_m: float = 0.0
    edge_source: str = "density"  # density | map | population_fallback

    def to_dict(self) -> dict:
        return asdict(self)


def stamp_prefab_root_y(surface_game_y: int, foundation_offset_blocks: int = 0) -> int:
    """P3: prefab root Y on real surface (mirrors C# StampSurfaceY.PrefabRootY)."""
    y = int(surface_game_y) + int(foundation_offset_blocks)
    return 1 if y < 1 else y


def clamp_prefabs_in_chunk(requested: int, max_per_chunk: int = 4) -> int:
    """P6: density budget (mirrors C# DensityBudget.ClampPrefabsInChunk)."""
    if requested < 0:
        return 0
    cap = max(0, int(max_per_chunk))
    return requested if requested <= cap else cap


def meters_per_pixel(
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
    *,
    at_lat: float,
) -> tuple[float, float]:
    """Approximate (m/px_x, m/px_z) for equirectangular sample grid."""
    w = max(1, int(width))
    h = max(1, int(height))
    m_lat = 110_540.0
    m_lon = 111_320.0 * max(0.01, abs(math.cos(math.radians(at_lat))))
    mx = abs(east - west) / w * m_lon
    mz = abs(north - south) / h * m_lat
    return mx, mz


def measure_urban_edge_radius_m(
    density: np.ndarray,
    peak_y: int,
    peak_x: int,
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    frac_of_peak: float = 0.12,
    min_abs: float = 40.0,
    max_radius_m: float = 80_000.0,
    visited_scratch: np.ndarray | None = None,
) -> float:
    """Measure urban edge from density/built-up map data around a peak.

    Flood-fills the connected component of cells at/above a density contour
    (max of ``min_abs`` and ``frac_of_peak * peak``), then returns the
    maximum geodesic-ish distance (meters) from the peak to any cell in that
    blob. That distance is the discoverable "city edge" for map labels.

    This is the primary map-data source for edge_radius_m when GHSL/WorldPop
    or settlement Gaussians have been rasterized into ``density``.

    ``visited_scratch``: optional caller-owned (h, w) bool array reused across
    calls so repeated measurements on a world-size grid do not reallocate and
    re-zero the full mask per peak. The buffer is left all-False on return.
    """
    dens = np.asarray(density, dtype=np.float64)
    h, w = dens.shape
    if h < 1 or w < 1:
        return 0.0
    py = int(np.clip(peak_y, 0, h - 1))
    px = int(np.clip(peak_x, 0, w - 1))
    peak = float(dens[py, px])
    if peak <= 0:
        return 0.0
    thr = max(float(min_abs), float(frac_of_peak) * peak)

    lat = north - (py + 0.5) / h * (north - south)

    def _degenerate() -> float:
        # Degenerate peak: one sample → half a pixel as minimum footprint.
        mx, mz = meters_per_pixel(west, south, east, north, w, h, at_lat=lat)
        return float(max(150.0, 0.5 * max(mx, mz)))

    # 4-connected component of cells >= thr containing the peak, via scanline
    # flood fill: one Python step per horizontal run, marking whole runs with
    # numpy slices (a per-cell BFS stalls on world-size density maps).
    if dens[py, px] < thr:
        return _degenerate()

    visited = (
        np.zeros((h, w), dtype=bool)
        if visited_scratch is None
        else visited_scratch
    )
    stack: list[tuple[int, int]] = [(py, px)]
    while stack:
        y, x = stack.pop()
        if visited[y, x] or dens[y, x] < thr:
            continue
        x0 = x
        while x0 > 0 and dens[y, x0 - 1] >= thr and not visited[y, x0 - 1]:
            x0 -= 1
        x1 = x
        while x1 < w - 1 and dens[y, x1 + 1] >= thr and not visited[y, x1 + 1]:
            x1 += 1
        visited[y, x0 : x1 + 1] = True
        for ny in (y - 1, y + 1):
            if not (0 <= ny < h):
                continue
            seg = dens[ny, x0 : x1 + 1] >= thr
            seg &= ~visited[ny, x0 : x1 + 1]
            idxs = np.nonzero(seg)[0]
            if idxs.size == 0:
                continue
            # One seed per consecutive run; runs behind a visited gap in the
            # parent span are still reachable through this row's own seeds.
            starts = np.concatenate(([0], np.nonzero(np.diff(idxs) > 1)[0] + 1))
            for s in starts:
                nx_ = int(idxs[s]) + x0
                if not visited[ny, nx_]:
                    stack.append((ny, nx_))

    ys, xs = np.nonzero(visited)
    if visited_scratch is not None:
        # Reset only the touched cells: O(blob), not O(h*w) memset per core.
        visited[ys, xs] = False
    if ys.size <= 1:
        return _degenerate()

    mx, mz = meters_per_pixel(west, south, east, north, w, h, at_lat=lat)
    dx_m = (xs.astype(np.float64) - px) * mx
    dz_m = (ys.astype(np.float64) - py) * mz
    max_d = float(np.sqrt(dx_m * dx_m + dz_m * dz_m).max())
    return float(min(max_radius_m, max(150.0, max_d)))


def measure_edge_at_lonlat(
    density: np.ndarray,
    lon: float,
    lat: float,
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    search_px: int = 8,
) -> float:
    """Snap to local density max near lon/lat, then measure urban edge meters."""
    dens = np.asarray(density, dtype=np.float64)
    h, w = dens.shape
    if h < 1 or w < 1 or east <= west or north <= south:
        return 0.0
    fx = (lon - west) / (east - west)
    fz = (north - lat) / (north - south)
    cx = int(np.clip(fx * w, 0, w - 1))
    cy = int(np.clip(fz * h, 0, h - 1))
    y0 = max(0, cy - search_px)
    y1 = min(h, cy + search_px + 1)
    x0 = max(0, cx - search_px)
    x1 = min(w, cx + search_px + 1)
    window = dens[y0:y1, x0:x1]
    if window.size == 0:
        return 0.0
    iy, ix = np.unravel_index(int(np.argmax(window)), window.shape)
    return measure_urban_edge_radius_m(
        dens, y0 + int(iy), x0 + int(ix), west, south, east, north
    )


@dataclass(frozen=True, slots=True)
class PrefabStamp:
    name: str
    band: str
    world_x: int  # centered world coords for prefabs.xml
    world_z: int
    y: int
    rotation: int
    density_byte: int

    def to_dict(self) -> dict:
        return asdict(self)


def load_density_geotiff(
    path: Path,
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
    *,
    scale: float = 1.0,
) -> np.ndarray:
    """Sample a density GeoTIFF (people/km² or built-up) onto equirectangular grid.

    Requires rasterio (`uv pip install -e '.[gis]'`).
    """
    try:
        import rasterio
        from rasterio.warp import transform as rio_transform
    except ImportError as e:
        raise ImportError("install realearth-tools[gis] for density GeoTIFF support") from e

    lon, lat = grid_lonlat(west, south, east, north, width, height)
    with rasterio.open(path) as ds:
        if ds.crs and str(ds.crs) not in ("EPSG:4326", "OGC:CRS84"):
            xs, ys = rio_transform(
                "EPSG:4326", ds.crs, lon.ravel().tolist(), lat.ravel().tolist()
            )
            coords = list(zip(xs, ys, strict=True))
        else:
            coords = list(zip(lon.ravel().tolist(), lat.ravel().tolist(), strict=True))
        samples = list(ds.sample(coords))
        vals = np.array([s[0] for s in samples], dtype=np.float64).reshape(height, width)
        if ds.nodata is not None:
            vals = np.where(vals == ds.nodata, 0.0, vals)
        vals = np.nan_to_num(vals, nan=0.0) * scale
    return np.clip(vals, 0, None)


def combine_population_and_built(
    population: np.ndarray,
    built_up: np.ndarray | None = None,
) -> np.ndarray:
    """Combine people/km² with optional built-up fraction (0-1 or 0-100).

    Built-up boosts urban intensity so dense suburbs without huge pop still stamp.
    """
    pop = np.asarray(population, dtype=np.float64)
    if built_up is None:
        return pop
    b = np.asarray(built_up, dtype=np.float64)
    if np.nanmax(b) > 1.5:
        b = b / 100.0  # percent → fraction
    b = np.clip(b, 0, 1)
    # Effective density: pop * (0.35 + 0.65*built) + built*8000 as floor for dense fabric
    return pop * (0.35 + 0.65 * b) + b * 8000.0


def density_to_band(peak: float) -> str:
    if peak >= 15000:
        return "metro"
    if peak >= 5000:
        return "large_city"
    if peak >= 1500:
        return "town"
    if peak >= 400:
        return "village"
    if peak >= 80:
        return "hamlet"
    return "rural_scatter"


def detect_city_cores(
    density: np.ndarray,
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    min_peak: float = 80.0,
    min_separation_px: int = 24,
    settlements: list[Settlement] | None = None,
    max_cores: int = 80,
) -> list[CityCore]:
    """Find density peaks as city/town cores; snap names from nearby settlements."""
    dens = np.asarray(density, dtype=np.float64)
    h, w = dens.shape
    if h < 3 or w < 3:
        return []

    # Simple local-max filter
    from numpy.lib.stride_tricks import sliding_window_view

    pad = np.pad(dens, 1, mode="edge")
    windows = sliding_window_view(pad, (3, 3))
    center = dens
    is_max = center >= windows.max(axis=(-1, -2)) - 1e-6
    is_max &= center >= min_peak
    ys, xs = np.where(is_max)
    peaks = sorted(
        [(float(center[y, x]), int(y), int(x)) for y, x in zip(ys, xs, strict=True)],
        reverse=True,
    )

    chosen: list[tuple[float, int, int]] = []
    for peak, y, x in peaks:
        if any(
            abs(y - cy) < min_separation_px and abs(x - cx) < min_separation_px
            for _, cy, cx in chosen
        ):
            continue
        chosen.append((peak, y, x))
        if len(chosen) >= max_cores:
            break

    cores: list[CityCore] = []
    # One flood-fill mask reused across cores: allocating + zeroing a fresh
    # (h, w) bool grid per peak costs O(cores * h * w) memset on world-size
    # density maps; reuse keeps it O(h * w) total.
    visited_scratch = np.zeros((h, w), dtype=bool)
    for peak, y, x in chosen:
        lon = west + (x + 0.5) / w * (east - west)
        lat = north - (y + 0.5) / h * (north - south)
        name = f"settlement_{len(cores)+1}"
        pop_est = int(peak * 4.0)  # rough people from density peak
        best = None
        best_d = 1e9
        edge_m = measure_urban_edge_radius_m(
            dens, y, x, west, south, east, north,
            visited_scratch=visited_scratch,
        )
        edge_src = "density"
        if settlements:
            for s in settlements:
                d = (s.lon - lon) ** 2 + (s.lat - lat) ** 2
                if d < best_d:
                    best_d = d
                    best = s
            # ~0.35 deg ≈ 30 km at mid-latitudes, loose match
            if best is not None and best_d < (0.35**2):
                name = best.name
                pop_est = max(pop_est, best.population)
                # Prefer explicit map extent on the settlement (polygon/bbox/radius).
                if best.edge_radius_m is not None and best.edge_radius_m > 0:
                    edge_m = float(best.edge_radius_m)
                    edge_src = "map"
        band = density_to_band(peak)
        if settlements and best is not None and best_d < (0.35**2):
            band = best.band if best.population else band
        if edge_m <= 0:
            edge_m = urban_radius_m_from_population(pop_est)
            edge_src = "population_fallback"
        cores.append(
            CityCore(
                name=name,
                lon=lon,
                lat=lat,
                population=pop_est,
                band=band,
                peak_density=peak,
                built_up=min(1.0, peak / 20000.0),
                local_x=x,
                local_z=y,
                edge_radius_m=float(edge_m),
                edge_source=edge_src,
            )
        )
    return cores


def _game_y_as_int32(game_y: np.ndarray) -> np.ndarray:
    """Preserve real surface Y (H500/Everest). Never cast to uint8 (wraps 500→244)."""
    gy = np.asarray(game_y)
    if np.issubdtype(gy.dtype, np.floating):
        return np.rint(gy).astype(np.int32)
    # uint8/uint16 promote without wrap; int already safe
    return gy.astype(np.int32, copy=False)


def stamp_prefabs_from_density(
    density_byte: np.ndarray,
    game_y: np.ndarray,
    *,
    world_size: int,
    sea_level: int = 32,
    cores: list[CityCore] | None = None,
    seed: int = 7,
    max_prefabs_per_chunk: int = 4,
) -> list[PrefabStamp]:
    """Place vanilla POIs denser where population/built-up is high.

    ``game_y`` must carry real surface heights as int/float (not uint8) for tall
    columns (H500 gameY=500, Everest ≈8949). Stamps use :func:`stamp_prefab_root_y`.
    Per 16×16 world-chunk counts are capped via :func:`clamp_prefabs_in_chunk` (P6).
    """
    rng = np.random.default_rng(seed)
    dens = np.asarray(density_byte, dtype=np.uint8)
    gy = _game_y_as_int32(game_y)
    h, w = dens.shape
    half = world_size // 2
    stamps: list[PrefabStamp] = []
    chunk_counts: dict[tuple[int, int], int] = {}

    # Scale sample grid → world blocks if density map != world size
    def to_world(ix: int, iz: int) -> tuple[int, int]:
        wx = int(ix / max(1, w - 1) * (world_size - 1)) - half
        wz = int(iz / max(1, h - 1) * (world_size - 1)) - half
        return wx, wz

    def elev_at(ix: int, iz: int) -> int:
        return int(gy[min(h - 1, max(0, iz)), min(w - 1, max(0, ix))])

    def try_add(stamp: PrefabStamp) -> bool:
        """P6: enforce DensityBudget.ClampPrefabsInChunk per world chunk."""
        cx = stamp.world_x // 16
        cz = stamp.world_z // 16
        key = (cx, cz)
        n = chunk_counts.get(key, 0)
        allowed = clamp_prefabs_in_chunk(n + 1, max_prefabs_per_chunk)
        if allowed <= n:
            return False
        chunk_counts[key] = allowed
        stamps.append(stamp)
        return True

    # Grid scan with local spacing from density
    y = 4
    while y < h - 4:
        x = 4
        row_step = 80
        while x < w - 4:
            d = int(dens[y, x])
            elev = elev_at(x, y)
            if elev <= sea_level + 1 or d < 25:
                x += 40
                continue
            # band from density byte
            if d >= 180:
                band = "metro"
            elif d >= 140:
                band = "large_city"
            elif d >= 100:
                band = "town"
            elif d >= 70:
                band = "village"
            elif d >= 40:
                band = "hamlet"
            else:
                band = "rural_scatter"
            spacing = SPACING_BLOCKS[band]
            # convert spacing from world blocks to sample pixels
            px_spacing = max(3, int(spacing * w / world_size))
            pool = PREFAB_POOLS[band]
            prefab = pool[int(rng.integers(0, len(pool)))]
            wx, wz = to_world(x, y)
            try_add(
                PrefabStamp(
                    name=prefab,
                    band=band,
                    world_x=wx,
                    world_z=wz,
                    y=stamp_prefab_root_y(elev),
                    rotation=int(rng.integers(0, 4)),
                    density_byte=d,
                )
            )
            x += px_spacing
            row_step = min(row_step, px_spacing)
        y += max(3, row_step)

    # Ensure each city core gets a cluster center stamp
    if cores:
        for c in cores:
            pool = PREFAB_POOLS.get(c.band, PREFAB_POOLS["town"])
            prefab = pool[0]
            elev = elev_at(c.local_x, c.local_z)
            if elev <= sea_level:
                elev = sea_level + 3
            wx, wz = to_world(c.local_x, c.local_z)
            try_add(
                PrefabStamp(
                    name=prefab,
                    band=c.band,
                    world_x=wx,
                    world_z=wz,
                    y=stamp_prefab_root_y(elev),
                    rotation=0,
                    density_byte=min(255, int(c.peak_density / 50)),
                )
            )
            # ring of fillers around core
            for k in range(4 if c.band in ("metro", "large_city") else 2):
                ang = k * (math.pi / 2)
                r = 40 + k * 20
                sx = int(c.local_x + (r * w / world_size) * math.cos(ang))
                sz = int(c.local_z + (r * h / world_size) * math.sin(ang))
                if 0 <= sx < w and 0 <= sz < h and elev_at(sx, sz) > sea_level + 1:
                    wxx, wzz = to_world(sx, sz)
                    try_add(
                        PrefabStamp(
                            name=pool[int(rng.integers(0, len(pool)))],
                            band=c.band,
                            world_x=wxx,
                            world_z=wzz,
                            y=stamp_prefab_root_y(elev_at(sx, sz)),
                            rotation=int(rng.integers(0, 4)),
                            density_byte=min(255, int(c.peak_density / 50)),
                        )
                    )

    # Deduplicate close stamps (budget already applied at add time)
    stamps = _dedupe_stamps(stamps, min_dist=20)
    return stamps


def _dedupe_stamps(stamps: list[PrefabStamp], min_dist: int = 20) -> list[PrefabStamp]:
    out: list[PrefabStamp] = []
    for s in stamps:
        if any(
            abs(s.world_x - o.world_x) < min_dist and abs(s.world_z - o.world_z) < min_dist
            for o in out
        ):
            continue
        out.append(s)
    return out


def write_prefabs_xml(path: Path, stamps: list[PrefabStamp]) -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<prefabs>"]
    for s in stamps:
        # y from terrain; rotation 0-3 as RWG uses
        lines.append(
            f'  <decoration type="model" name="{s.name}" '
            f'position="{s.world_x},{s.y},{s.world_z}" rotation="{s.rotation}" />'
        )
    lines.append("</prefabs>\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_cities_json(path: Path, cores: list[CityCore], stamps: list[PrefabStamp]) -> None:
    path.write_text(
        json.dumps(
            {
                "cores": [c.to_dict() for c in cores],
                "prefab_count": len(stamps),
                "stamps_sample": [s.to_dict() for s in stamps[:50]],
                "sources_note": (
                    "Density from settlement Gaussians and/or GHSL/WorldPop GeoTIFF; "
                    "not Google building footprints."
                ),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def apply_urban_from_density(
    landcover: np.ndarray,
    density_byte: np.ndarray,
    *,
    urban_threshold: int = 90,
) -> np.ndarray:
    out = np.array(landcover, copy=True)
    urban = density_byte >= urban_threshold
    land = out != int(LandCover.OCEAN)
    out[urban & land] = int(LandCover.URBAN)
    return out


def build_density_field(
    width: int,
    height: int,
    west: float,
    south: float,
    east: float,
    north: float,
    settlements: list[Settlement],
    *,
    population_geotiff: Path | None = None,
    built_geotiff: Path | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (people_per_km2 float grid, density_byte uint8)."""
    dens = paint_settlement_density(width, height, west, south, east, north, settlements)
    if population_geotiff is not None:
        dens = load_density_geotiff(
            population_geotiff, west, south, east, north, width, height
        )
    built = None
    if built_geotiff is not None:
        built = load_density_geotiff(built_geotiff, west, south, east, north, width, height)
        # If values look like square meters of built surface, normalize roughly
        if np.nanmax(built) > 1.5:
            built = built / (np.nanmax(built) + 1e-6)
    dens = combine_population_and_built(dens, built)
    return dens, population_to_byte(dens)
