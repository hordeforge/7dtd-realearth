"""Settlements, population density, and POI planning for tiles."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from realearth import JsonDict

# C0 controls, DEL, C1: never legitimate in a place name. Stripped at ingestion
# so a hostile pack cannot carry CR/LF into the runtime's server-log output.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# GeoJSON rings nest one level per polygon part; a real export never goes past a
# handful. Beyond this the nesting is malformed, and walking it further only
# costs memory.
MAX_COORD_NESTING = 64
LON_LIMIT = 180.0
LAT_LIMIT = 90.0
# A tile's POI blob holds a handful of settlements; 1 MiB is orders of magnitude
# above any real tile and keeps a hostile pack from turning decode into work.
MAX_POI_BLOB_BYTES = 1 << 20


def normalize_place_name(name: str) -> str:
    """Canonical form for place-name identity: NFC so NFD input (macOS filenames,
    some map exports) matches the NFC seed names instead of duplicating labels.
    Also strips C0/C1 control chars (mirrors Source/RealEarth CityMapLabels):
    names are echoed into the dedicated server log at runtime, so raw CR/LF/TAB
    decoded from pack JSON would let a hostile pack forge log lines."""
    return _CONTROL_CHARS_RE.sub("", unicodedata.normalize("NFC", name))


@dataclass(frozen=True, slots=True)
class Settlement:
    name: str
    lon: float
    lat: float
    population: int
    kind: str = "city"  # city | town | village | hamlet
    # Urban footprint half-width in meters from map data (density/built-up/polygon).
    # None → not measured yet; use paint fallback or leave for runtime.
    edge_radius_m: float | None = None

    @property
    def band(self) -> str:
        # Single population→band ladder shared with the runtime fallback
        # (Source/RealEarth/RuntimePoiInject.cs BandFromPop): a place must get the
        # same band whether it arrives via settlements.json or via the runtime's
        # missing-band fallback, because band selects the runtime prefab pool.
        p = self.population
        if p >= 1_000_000:
            return "metro"
        if p >= 100_000:
            return "large_city"
        if p >= 10_000:
            return "town"
        if p >= 1_000:
            return "village"
        if p >= 100:
            return "hamlet"
        return "rural_scatter"

    def effective_edge_radius_m(self) -> float:
        """Map-derived edge if present; else population paint radius (last resort)."""
        if self.edge_radius_m is not None and self.edge_radius_m > 0:
            return float(self.edge_radius_m)
        return urban_radius_m_from_population(self.population)


def urban_radius_m_from_population(population: int) -> float:
    """Last-resort footprint when no density/polygon extent is available.

    Matches the historical Gaussian paint scale: radius_km = clamp(sqrt(pop)/40, 1.5, 80).
    Prefer measure_urban_edge_radius_m / GeoJSON edge fields in real packs.
    """
    radius_km = max(1.5, min(80.0, math.sqrt(max(int(population), 1)) / 40.0))
    return radius_km * 1000.0


def meters_per_degree(lat: float) -> tuple[float, float]:
    """Approximate (m/deg_lat, m/deg_lon) at |lat|; one copy for all edge math."""
    m_lat = 110_540.0
    m_lon = 111_320.0 * max(0.01, abs(math.cos(math.radians(lat))))
    return m_lat, m_lon


def edge_radius_m_from_bbox(
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    center_lon: float | None = None,
    center_lat: float | None = None,
) -> float:
    """Approximate urban radius from a lon/lat bbox in meters.

    Max of the E-W and N-S half-widths and 0.85x the center-to-corner distance
    (covers skewed boxes where a half-width undershoots the real extent).

    Used when settlement data ships a real urban-area bounding box
    (e.g. Natural Earth urban areas, OSM multipolygon envelope).
    """
    if east <= west or north <= south:
        return 0.0
    clon = center_lon if center_lon is not None else 0.5 * (west + east)
    clat = center_lat if center_lat is not None else 0.5 * (south + north)
    m_lat, m_lon = meters_per_degree(clat)
    half_w = 0.5 * abs(east - west) * m_lon
    half_h = 0.5 * abs(north - south) * m_lat
    # also consider corner distance from center (skewed boxes)
    d_corner = math.hypot((east - clon) * m_lon, (north - clat) * m_lat)
    return float(max(half_w, half_h, d_corner * 0.85))


def _prop_float(props: JsonDict, *keys: str) -> float | None:
    for k in keys:
        if k in props and props[k] is not None and props[k] != "":
            try:
                v = float(props[k])
            except (TypeError, ValueError):
                continue
            # NaN/Inf in a size field poisons every downstream radius; drop it.
            if math.isfinite(v):
                return v
    return None


def edge_radius_m_from_properties(props: JsonDict, lon: float, lat: float) -> float | None:
    """Extract urban edge meters from GeoJSON/JSON properties (map data fields)."""
    direct = _prop_float(
        props,
        "edge_radius_m",
        "edge_radius_meters",
        "radius_m",
        "urban_radius_m",
    )
    if direct is not None and direct > 0:
        return direct
    km = _prop_float(props, "edge_radius_km", "radius_km", "urban_radius_km")
    if km is not None and km > 0:
        return km * 1000.0
    # bbox as [west, south, east, north] or separate keys
    bbox = props.get("bbox") or props.get("extent")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            west, south, east, north = (float(v) for v in bbox[:4])
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(v) for v in (west, south, east, north)):
            return None
        return edge_radius_m_from_bbox(
            west,
            south,
            east,
            north,
            center_lon=lon,
            center_lat=lat,
        )
    w = _prop_float(props, "west", "min_lon", "lon_min")
    s = _prop_float(props, "south", "min_lat", "lat_min")
    e = _prop_float(props, "east", "max_lon", "lon_max")
    n = _prop_float(props, "north", "max_lat", "lat_max")
    if None not in (w, s, e, n):
        return edge_radius_m_from_bbox(w, s, e, n, center_lon=lon, center_lat=lat)  # type: ignore[arg-type]
    return None


# Small built-in seed set for demos (real coordinates, approximate populations).
# edge_radius_m ≈ half-width of real urban continuum (order-of-magnitude from map extents).
SEED_SETTLEMENTS: list[Settlement] = [
    Settlement("New York", -74.006, 40.7128, 8_300_000, edge_radius_m=35_000),
    Settlement("Los Angeles", -118.2437, 34.0522, 3_900_000, edge_radius_m=45_000),
    Settlement("Chicago", -87.6298, 41.8781, 2_700_000, edge_radius_m=28_000),
    Settlement("London", -0.1276, 51.5074, 9_000_000, edge_radius_m=28_000),
    Settlement("Paris", 2.3522, 48.8566, 2_100_000, edge_radius_m=18_000),
    Settlement("Berlin", 13.4050, 52.5200, 3_700_000, edge_radius_m=16_000),
    Settlement("Tokyo", 139.6917, 35.6895, 14_000_000, edge_radius_m=40_000),
    Settlement("Sydney", 151.2093, -33.8688, 5_300_000, edge_radius_m=22_000),
    Settlement("São Paulo", -46.6333, -23.5505, 12_000_000, edge_radius_m=30_000),
    Settlement("Cairo", 31.2357, 30.0444, 10_000_000, edge_radius_m=22_000),
    Settlement("Mumbai", 72.8777, 19.0760, 12_500_000, edge_radius_m=25_000),
    Settlement("Denver", -104.9903, 39.7392, 715_000, edge_radius_m=22_000),
    Settlement("Phoenix", -112.0740, 33.4484, 1_600_000, edge_radius_m=35_000),
    Settlement("Seattle", -122.3321, 47.6062, 750_000, edge_radius_m=20_000),
    Settlement("Miami", -80.1918, 25.7617, 450_000, edge_radius_m=25_000),
    Settlement("Rome", 12.4964, 41.9028, 2_800_000, edge_radius_m=12_000),
    Settlement("Moscow", 37.6173, 55.7558, 12_500_000, edge_radius_m=25_000),
    Settlement("Beijing", 116.4074, 39.9042, 21_000_000, edge_radius_m=35_000),
    Settlement("Cape Town", 18.4241, -33.9249, 460_000, edge_radius_m=15_000),
    Settlement("Reykjavik", -21.8174, 64.1466, 140_000, edge_radius_m=8_000),
    Settlement("Kathmandu", 85.3240, 27.7172, 1_400_000, edge_radius_m=10_000),
    Settlement("Namche Bazaar", 86.7140, 27.8069, 1_600, edge_radius_m=800),
    Settlement("Lukla", 86.7314, 27.6866, 1_500, edge_radius_m=600),
    Settlement("Dingboche", 86.8360, 27.8920, 200, edge_radius_m=400),
    Settlement("Base Camp", 86.8525, 28.0026, 50, edge_radius_m=300),
]


def _collect_ring_coords(c: Any, lons: list[float], lats: list[float]) -> None:
    """Flatten nested GeoJSON coordinate arrays into lon/lat lists.

    Iterative with an explicit nesting limit: a hostile or broken export can
    nest rings arbitrarily deep, and a recursive walk turns that into a
    RecursionError that takes the whole build down.
    """
    stack: list[tuple[Any, int]] = [(c, 0)]
    while stack:
        node, depth = stack.pop()
        if not node or depth > MAX_COORD_NESTING:
            continue
        head = node[0]
        if isinstance(head, (int, float)) and not isinstance(head, bool):
            if len(node) >= 2:
                lon, lat = float(node[0]), float(node[1])
                if math.isfinite(lon) and math.isfinite(lat):
                    lons.append(lon)
                    lats.append(lat)
            continue
        if isinstance(node, (list, tuple)):
            stack.extend((part, depth + 1) for part in node)


def _lon_lat(value: float) -> bool:
    """True when a coordinate is a real position on the globe."""
    return (
        math.isfinite(value)
        and LON_LIMIT >= value >= -LON_LIMIT
        and LAT_LIMIT >= value >= -LAT_LIMIT
    )


def _prop_int(props: JsonDict, *keys: str) -> int:
    for k in keys:
        raw = props.get(k)
        if raw is None or raw == "":
            continue
        try:
            pop = int(raw)
        except (TypeError, ValueError):
            continue
        if pop > 0:
            return pop
    return 0


def load_settlements_geojson(path: Path) -> list[Settlement]:
    """Load settlements from a simple GeoJSON FeatureCollection.

    Expected properties: name, population (optional), kind (optional).
    Geometry: Point [lon, lat], or Polygon/MultiPolygon (centroid + edge from bbox).
    Map extent: edge_radius_m / radius_km / bbox / west|south|east|north.

    The file is external input (downloaded map data, a pack from a mirror), so
    every field is type-checked: a feature that is not a well-formed Point or
    Polygon with finite in-range coordinates is skipped rather than raising
    deep inside the parse. Only unparsable JSON raises (ValueError).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a GeoJSON object")
    features = data.get("features")
    if features is None:
        return []
    if not isinstance(features, list):
        raise ValueError(f"{path}: 'features' is not a list")
    out: list[Settlement] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry")
        props = feat.get("properties")
        geom = geom if isinstance(geom, dict) else {}
        props = props if isinstance(props, dict) else {}
        gtype = geom.get("type")
        lon = lat = None
        edge_from_poly: float | None = None

        if gtype == "Point":
            coords = geom.get("coordinates")
            if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                continue
            try:
                lon, lat = float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                continue
        elif gtype in ("Polygon", "MultiPolygon"):
            # Centroid + edge from polygon envelope (real urban area polygons).
            lons: list[float] = []
            lats: list[float] = []
            _collect_ring_coords(geom.get("coordinates"), lons, lats)
            if not lons:
                continue
            lon = sum(lons) / len(lons)
            lat = sum(lats) / len(lats)
            edge_from_poly = edge_radius_m_from_bbox(
                min(lons),
                min(lats),
                max(lons),
                max(lats),
                center_lon=lon,
                center_lat=lat,
            )
        else:
            continue

        if lon is None or lat is None or not (_lon_lat(lon) and _lon_lat(lat)):
            continue

        name = str(props.get("name") or props.get("NAME") or "unknown")
        pop = _prop_int(props, "population", "POP_MAX")
        kind = str(props.get("kind") or props.get("featurecla") or "city")
        edge = edge_radius_m_from_properties(props, lon, lat)
        if edge is None:
            edge = edge_from_poly
        out.append(
            Settlement(
                name=normalize_place_name(name),
                lon=lon,
                lat=lat,
                population=pop,
                kind=normalize_place_name(kind),
                edge_radius_m=edge,
            )
        )
    return out


def settlement_to_json_dict(s: Settlement) -> JsonDict:
    d: JsonDict = {
        "name": s.name,
        "lon": s.lon,
        "lat": s.lat,
        "population": s.population,
        "band": s.band,
        "edge_radius_m": round(s.effective_edge_radius_m(), 1),
    }
    if s.edge_radius_m is not None:
        d["edge_source"] = "map"
    else:
        d["edge_source"] = "population_fallback"
    return d


def population_to_byte(population_per_km2: np.ndarray) -> np.ndarray:
    """Log-scale people/km² into 0-255 for the tile channel."""
    p = np.asarray(population_per_km2, dtype=np.float64)
    p = np.clip(p, 0, None)
    # 0 → 0, 1 → ~15, 100 → ~100, 10000 → ~200, ~126000+ → 255
    scaled = np.where(p <= 0, 0.0, 20.0 * np.log10(p + 1.0) * 2.5)
    return np.clip(np.rint(scaled), 0, 255).astype(np.uint8)


def paint_settlement_density(
    width: int,
    height: int,
    west: float,
    south: float,
    east: float,
    north: float,
    settlements: list[Settlement],
) -> np.ndarray:
    """Rasterize approximate population density from point settlements.

    Uses a Gaussian falloff in lon/lat space (not perfect geodesy; fine for stamping).

    Each Gaussian is painted only inside its ±clip_sigma window. Beyond
    clip_sigma the contribution is < peak * exp(-clip_sigma²) ≈ 1e-13 * peak,
    which is below float64 significance of the accumulated field, so results
    match an unrestricted full-grid paint to within rounding noise.
    """
    clip_sigma = 6.0

    dens = np.zeros((height, width), dtype=np.float64)
    lon_step = (east - west) / width
    lat_step = (south - north) / height  # negative: row 0 is north

    for s in settlements:
        if not (west <= s.lon <= east and south <= s.lat <= north):
            # still allow edge bleed
            if abs(s.lon - (west + east) / 2) > (east - west) * 1.5:
                continue
            if abs(s.lat - (south + north) / 2) > (north - south) * 1.5:
                continue
        # Prefer map-derived urban edge (m); else population fallback.
        radius_km = s.effective_edge_radius_m() / 1000.0
        # deg lat ~ 111 km
        r_lat = radius_km / 111.0
        r_lon = radius_km / max(1e-3, 111.0 * abs(math.cos(math.radians(s.lat))))
        if r_lat <= 0 or r_lon <= 0:
            continue
        peak = max(s.population, 1) / max(math.pi * radius_km * radius_km, 1.0)

        # Pixel window around the settlement center (pixel centers at +step/2).
        fx = (s.lon - west) / lon_step - 0.5
        fz = (s.lat - north) / lat_step - 0.5
        half_x = int(clip_sigma * r_lon / abs(lon_step)) + 1
        half_z = int(clip_sigma * r_lat / abs(lat_step)) + 1
        x0 = max(0, int(math.floor(fx)) - half_x)
        x1 = min(width, int(math.ceil(fx)) + half_x + 1)
        z0 = max(0, int(math.floor(fz)) - half_z)
        z1 = min(height, int(math.ceil(fz)) + half_z + 1)
        if x0 >= x1 or z0 >= z1:
            continue

        lon_w = np.linspace(west, east, width, endpoint=False)[x0:x1] + lon_step / 2
        lat_w = np.linspace(north, south, height, endpoint=False)[z0:z1] + lat_step / 2
        lon_g, lat_g = np.meshgrid(lon_w, lat_w)
        d2 = ((lon_g - s.lon) / r_lon) ** 2 + ((lat_g - s.lat) / r_lat) ** 2
        dens[z0:z1, x0:x1] += peak * np.exp(-d2)

    return dens


def encode_poi_blob(plan: list[JsonDict]) -> bytes:
    # ensure_ascii=False: POI names are real UTF-8 in the .rte blob (C# decodes
    # with Encoding.UTF8), not \uXXXX escapes.
    return json.dumps({"pois": plan}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode_poi_blob(blob: bytes) -> list[JsonDict]:
    """Decode a tile's POI blob. Only ValueError escapes a malformed blob.

    The blob travels inside a .rte tile, so a pack from a mirror or a share
    controls it: oversized, non-UTF-8, non-object and non-list payloads are all
    rejected here rather than surfacing as AttributeError/TypeError deeper in
    the pipeline.
    """
    if not blob:
        return []
    if len(blob) > MAX_POI_BLOB_BYTES:
        raise ValueError(f"poi blob too large: {len(blob)} > {MAX_POI_BLOB_BYTES} bytes")
    doc = json.loads(blob.decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("poi blob is not a JSON object")
    pois = doc.get("pois", [])
    if not isinstance(pois, list):
        raise ValueError("poi blob 'pois' is not a list")
    return [p for p in pois if isinstance(p, dict)]
