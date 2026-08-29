"""Deterministic road/river corridor stamping for region packs.

Burns linear features (roads, rivers, rail) from a GeoJSON LineString layer
into the landcover and population arrays of a region before tiling. Conflict
rules are explicit and deterministic:

1. River (INLAND_WATER) beats landcover but NOT road: a road crossing a river
   keeps the road cells (bridge semantics, no ford/water hybrid).
2. Road beats everything except OCEAN: roads never paint over open ocean
   (a ferry route is not a bridge).
3. Population is zeroed under road cells (no houses in the carriageway) and
   kept under river cells (riverside population survives).
4. Rail is treated like road for landcover (no population clearing is needed:
   rail bands are corridors too, same rule).

Input GeoJSON: FeatureCollection of LineString features; each feature has
`properties.kind` in {road, river, rail} (default road). Coordinates are
[lon, lat] pairs (RFC 7946). A non-LineString feature is skipped with a
warning; a missing/invalid geometry fails the build loudly so a bad input
file cannot silently produce an un-stamped pack.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from realearth.landcover import LandCover

# Corridor half-width in pixels at the region's native sampling resolution
# (a road is ~1-2 cells; rivers are wider). Scale with resolution later.
ROAD_HALF_WIDTH_PX = 1
RIVER_HALF_WIDTH_PX = 2


@dataclass(frozen=True)
class CorridorLayer:
    """Linear features normalized into pixel-space segments."""

    segments: tuple[tuple[tuple[float, float], tuple[float, float]], ...]
    kind: str

    @property
    def half_width(self) -> int:
        return RIVER_HALF_WIDTH_PX if self.kind == "river" else ROAD_HALF_WIDTH_PX


def load_corridors(path: Path) -> list[CorridorLayer]:
    """Parse a GeoJSON FeatureCollection of LineString corridors.

    Raises ValueError on malformed input (never silently skips a feature whose
    geometry type or coordinate count is wrong: a bad file must fail the build).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("type") != "FeatureCollection":
        raise ValueError(f"corridor file {path}: expected a GeoJSON FeatureCollection")
    features = raw.get("features") or []
    layers: dict[str, list[tuple[tuple[float, float], tuple[float, float]]]] = {}
    for i, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ValueError(f"corridor feature #{i}: not an object")
        props = feature.get("properties") or {}
        kind = str(props.get("kind") or "road")
        if kind not in ("road", "river", "rail"):
            raise ValueError(f"corridor feature #{i}: unknown kind {kind!r}")
        geom = feature.get("geometry") or {}
        if geom.get("type") != "LineString":
            raise ValueError(
                f"corridor feature #{i}: expected LineString, got {geom.get('type')!r}"
            )
        coords = geom.get("coordinates") or []
        pts: list[tuple[float, float]] = []
        for lonlat in coords:
            if not isinstance(lonlat, list) or len(lonlat) < 2:
                raise ValueError(f"corridor feature #{i}: bad coordinate {lonlat!r}")
            pts.append((float(lonlat[0]), float(lonlat[1])))
        if len(pts) < 2:
            raise ValueError(f"corridor feature #{i}: LineString needs >= 2 points")
        segs = layers.setdefault(kind, [])
        for seg_i in range(len(pts) - 1):
            a, b = pts[seg_i], pts[seg_i + 1]
            segs.append((a, b))
    return [CorridorLayer(tuple(layers.get(kind, ())), kind) for kind in ("road", "river", "rail")]


def _lonlat_to_px(
    lon: float, lat: float, west: float, north: float, per_lon: float, per_lat: float
) -> tuple[float, float]:
    """Equirectangular projection to pixel coords (row = +lat up, col = +lon)."""
    x = (lon - west) * per_lon
    y = (north - lat) * per_lat
    return x, y


def stamp_corridors(
    landcover: np.ndarray,
    population: np.ndarray,
    corridors: list[CorridorLayer],
    *,
    west: float,
    north: float,
    per_lon: float,
    per_lat: float,
) -> None:
    """Stamp corridors into landcover/population in place (deterministic).

    Rules (documented at module top):
    - road/rail beats river (bridge); river beats other landcover.
    - road/rail beats everything except OCEAN; river never paints ocean.
    - population zeroed under road/rail; kept under river.
    All writes are idempotent: re-stamping the same corridor yields the same
    result, and overlapping features apply the same rule regardless of order.
    """
    h, w = landcover.shape
    for layer in corridors:
        for a, b in layer.segments:
            x0, y0 = _lonlat_to_px(a[0], a[1], west, north, per_lon, per_lat)
            x1, y1 = _lonlat_to_px(b[0], b[1], west, north, per_lon, per_lat)
            # Bresenham-style line with a half-width brush (deterministic).
            steps = max(1, int(round(max(abs(x1 - x0), abs(y1 - y0)))))
            for t in range(steps + 1):
                cx = int(round(x0 + (x1 - x0) * t / steps))
                cy = int(round(y0 + (y1 - y0) * t / steps))
                for dy in range(-layer.half_width, layer.half_width + 1):
                    for dx in range(-layer.half_width, layer.half_width + 1):
                        px, py = cx + dx, cy + dy
                        if px < 0 or py < 0 or px >= w or py >= h:
                            continue
                        if layer.kind in ("road", "rail"):
                            if landcover[py, px] == LandCover.OCEAN:
                                continue  # rule 2: never paint open ocean
                            landcover[py, px] = LandCover.URBAN
                            population[py, px] = 0  # rule 3: no houses in road
                        else:  # river
                            if landcover[py, px] == LandCover.OCEAN:
                                continue
                            # rule 1: built land (URBAN) beats rivers (bridge);
                            # cropland and natural land give way to water.
                            if landcover[py, px] == LandCover.URBAN:
                                continue
                            landcover[py, px] = LandCover.INLAND_WATER
