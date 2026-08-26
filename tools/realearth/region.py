"""Build tile packs and region exports for a lon/lat bounding box."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from realearth import DEFAULT_TILE_SIZE, EARTH_CIRCUMFERENCE_M, EARTH_MERIDIAN_HALF_M
from realearth.coords import EarthGrid, lonlat_to_block
from realearth.density import (
    apply_urban_from_density,
    build_density_field,
    detect_city_cores,
    measure_edge_at_lonlat,
    write_cities_json,
)
from realearth.elevation import (
    fetch_region_geotiff,
    fetch_region_open_meteo,
    fetch_region_terrarium,
    grid_lonlat,
    synthetic_elevation,
)
from realearth.export_7dtd import export_region_pack
from realearth.landcover import classify_from_elevation_and_lat
from realearth.settlements import (
    SEED_SETTLEMENTS,
    Settlement,
    encode_poi_blob,
    normalize_place_name,
    settlement_to_json_dict,
)
from realearth.tile_format import (
    EarthTile,
    Manifest,
    tile_path,
    write_manifest,
    write_tile,
)


def _place_name_key(name: str) -> str:
    """Identity key for place names: NFC + casefold (never bare .lower())."""
    return normalize_place_name(name).casefold()


def build_region(
    west: float,
    south: float,
    east: float,
    north: float,
    out_dir: Path,
    *,
    resolution_m: float = 1.0,
    tile_size: int = DEFAULT_TILE_SIZE,
    source: str = "synthetic",
    settlements: list[Settlement] | None = None,
    name: str = "RealEarthRegion",
    also_export_7dtd: bool = True,
    max_dim: int = 4096,
    geotiff: Path | None = None,
    terrarium_zoom: int = 10,
    population_geotiff: Path | None = None,
    built_geotiff: Path | None = None,
) -> Manifest:
    """Generate tiles covering a bbox and optional vanilla heightmap export.

    resolution_m: meters per sample (1.0 = 1:1). Larger = coarser/faster.
    source: 'synthetic' | 'open_meteo' | 'terrarium' | 'geotiff'
    geotiff: path required when source='geotiff' (Copernicus/SRTM GeoTIFF)
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    settlements = settlements if settlements is not None else list(SEED_SETTLEMENTS)

    # Region size in meters (approx equirectangular at bbox center)
    mid_lat = (south + north) / 2
    import math

    m_per_deg_lat = EARTH_MERIDIAN_HALF_M / 180.0
    m_per_deg_lon = abs(math.cos(math.radians(mid_lat))) * (EARTH_CIRCUMFERENCE_M / 360.0)
    width_m = (east - west) * m_per_deg_lon
    height_m = (north - south) * m_per_deg_lat
    width = max(32, int(round(width_m / resolution_m)))
    height = max(32, int(round(height_m / resolution_m)))

    if max(width, height) > max_dim:
        scale = max(width, height) / max_dim
        width = max(32, int(width / scale))
        height = max(32, int(height / scale))
        resolution_m = resolution_m * scale

    if source == "open_meteo":
        elev = fetch_region_open_meteo(west, south, east, north, width, height)
        sources = ["Open-Meteo Elevation API (not Google)"]
    elif source == "terrarium":
        elev = fetch_region_terrarium(west, south, east, north, width, height, zoom=terrarium_zoom)
        sources = [
            "AWS Terrain Tiles / Mapzen Terrarium (open data, not Google Earth)",
        ]
    elif source == "geotiff":
        if geotiff is None:
            raise ValueError("source=geotiff requires geotiff= path to DEM GeoTIFF")
        elev = fetch_region_geotiff(Path(geotiff), west, south, east, north, width, height)
        sources = [f"GeoTIFF DEM: {Path(geotiff).name} (e.g. Copernicus GLO-30 / SRTM)"]
    elif source == "synthetic":
        elev = synthetic_elevation(width, height)
        sources = ["synthetic procedural (offline demo)"]
    else:
        raise ValueError(f"unknown source: {source} (use synthetic|open_meteo|terrarium|geotiff)")

    lon, lat = grid_lonlat(west, south, east, north, width, height)
    dens_f, pop = build_density_field(
        width,
        height,
        west,
        south,
        east,
        north,
        settlements,
        population_geotiff=population_geotiff,
        built_geotiff=built_geotiff,
    )
    urban = pop >= 90
    lc = classify_from_elevation_and_lat(elev, lat, urban_mask=urban)
    lc = apply_urban_from_density(lc, pop, urban_threshold=90)

    cores = detect_city_cores(
        dens_f, west, south, east, north, settlements=settlements, min_peak=80.0
    )
    write_cities_json(out_dir / "cities.json", cores, [])
    if population_geotiff:
        sources.append(f"Population GeoTIFF: {Path(population_geotiff).name}")
    if built_geotiff:
        sources.append(f"Built-up GeoTIFF: {Path(built_geotiff).name}")
    sources.append("City cores from density peaks + settlement points (not Google)")

    # Write as one or more tiles in a local (region) grid index space
    # For region packs we use a local origin at (0,0) for simplicity in demo tiles,
    # and store the geographic bbox in the manifest.
    tiles_meta: list[dict[str, int]] = []
    n_tx = (width + tile_size - 1) // tile_size
    n_tz = (height + tile_size - 1) // tile_size

    for tz in range(n_tz):
        for tx in range(n_tx):
            y0 = tz * tile_size
            x0 = tx * tile_size
            y1 = min(height, y0 + tile_size)
            x1 = min(width, x0 + tile_size)
            th = y1 - y0
            tw = x1 - x0
            # Pad edge tiles to full tile_size for uniform streaming
            elev_t = np.full((tile_size, tile_size), -100.0, dtype=np.float32)
            lc_t = np.full((tile_size, tile_size), 0, dtype=np.uint8)
            pop_t = np.zeros((tile_size, tile_size), dtype=np.uint8)
            elev_t[:th, :tw] = elev[y0:y1, x0:x1]
            lc_t[:th, :tw] = lc[y0:y1, x0:x1]
            pop_t[:th, :tw] = pop[y0:y1, x0:x1]

            # City cores + named settlements that fall in this tile.
            # A core snapped to a settlement name is the same place; stamping
            # both would place duplicate POIs at the same block (the
            # settlements.json dump below applies the same NFC+casefold rule).
            plan = []
            plan_names: set[str] = set()
            for c in cores:
                if x0 <= c.local_x < x0 + tw and y0 <= c.local_z < y0 + th:
                    plan_names.add(_place_name_key(c.name))
                    plan.append(
                        {
                            "name": c.name,
                            "band": c.band,
                            "population": c.population,
                            "peak_density": c.peak_density,
                            "edge_radius_m": c.edge_radius_m,
                            "edge_source": c.edge_source,
                            "local_x": c.local_x - x0,
                            "local_z": c.local_z - y0,
                            "lon": c.lon,
                            "lat": c.lat,
                        }
                    )
            for s in settlements:
                if not (west <= s.lon <= east and south <= s.lat <= north):
                    continue
                fx = (s.lon - west) / (east - west)
                fz = (north - s.lat) / (north - south)
                lx = int(fx * width) - x0
                lz = int(fz * height) - y0
                if 0 <= lx < tw and 0 <= lz < th and _place_name_key(s.name) not in plan_names:
                    plan_names.add(_place_name_key(s.name))
                    plan.append(
                        {
                            "name": s.name,
                            "band": s.band,
                            "population": s.population,
                            "edge_radius_m": s.effective_edge_radius_m(),
                            "local_x": lx,
                            "local_z": lz,
                            "lon": s.lon,
                            "lat": s.lat,
                        }
                    )

            tile = EarthTile(
                tile_x=tx,
                tile_z=tz,
                elevation_m=elev_t,
                landcover=lc_t,
                population=pop_t,
                poi_blob=encode_poi_blob(plan),
            )
            path = tile_path(out_dir, tx, tz)
            write_tile(path, tile)
            tiles_meta.append({"tx": tx, "tz": tz})

    manifest = Manifest(
        name=name,
        tile_size=tile_size,
        world_width=width,
        world_height=height,
        meters_per_block=resolution_m,
        bbox={"west": west, "south": south, "east": east, "north": north},
        tiles=tiles_meta,
        sources=sources
        + [
            "Natural Earth / built-in seed cities (demo)",
            "Heuristic landcover from elevation+latitude",
        ],
        notes=(
            f"Region pack {width}x{height} samples @ ~{resolution_m:.2f} m/sample. "
            "Full-planet packs use absolute EarthGrid indices; this demo uses local 0-based tiles."
        ),
    )
    write_manifest(out_dir / "earth.manifest.json", manifest)

    if also_export_7dtd:
        export_region_pack(
            elev,
            lc,
            out_dir / "export_7dtd",
            name=name,
        )

    # Human-readable settlement dump with map-derived urban edge (m).
    present = [s for s in settlements if west <= s.lon <= east and south <= s.lat <= north]
    settlement_rows = []
    for s in present:
        edge = s.edge_radius_m
        src = "map" if edge is not None and edge > 0 else None
        if edge is None or edge <= 0:
            measured = measure_edge_at_lonlat(dens_f, s.lon, s.lat, west, south, east, north)
            if measured > 0:
                edge = measured
                src = "density"
        # Match named core if closer measurement available
        for c in cores:
            if c.name == s.name and c.edge_radius_m > 0:
                edge = c.edge_radius_m
                src = c.edge_source
                break
        row_s = Settlement(
            name=s.name,
            lon=s.lon,
            lat=s.lat,
            population=s.population,
            kind=s.kind,
            edge_radius_m=edge,
        )
        d = settlement_to_json_dict(row_s)
        if src:
            d["edge_source"] = src
        settlement_rows.append(d)

    # Also emit unnamed density cores not already listed. Name key is NFC+casefold
    # so an NFD spelling of the same place does not produce a duplicate row.
    named = {_place_name_key(r["name"]) for r in settlement_rows}
    for c in cores:
        if _place_name_key(c.name) in named:
            continue
        settlement_rows.append(
            {
                "name": c.name,
                "lon": c.lon,
                "lat": c.lat,
                "population": c.population,
                "band": c.band,
                "edge_radius_m": round(c.edge_radius_m, 1),
                "edge_source": c.edge_source,
            }
        )

    (out_dir / "settlements.json").write_text(
        # ensure_ascii=False: names are identity text consumed by the in-game
        # map labels; store real UTF-8 instead of \uXXXX escapes.
        json.dumps(settlement_rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return manifest


def world_tile_indices_for_bbox(
    west: float,
    south: float,
    east: float,
    north: float,
    tile_size: int = DEFAULT_TILE_SIZE,
) -> list[tuple[int, int]]:
    """Absolute Earth tile indices for a bbox (for full-planet pipelines).

    Raises ValueError on non-finite or inverted bounds (east>west, north>south),
    mirroring the `planet-tiles` CLI. An antimeridian-straddling bbox given as
    west > east would otherwise expand to a near-full-planet span and hang.
    """
    if east <= west or north <= south:
        raise ValueError(
            f"bbox must have east>west and north>south, got {west},{south} -> {east},{north}"
        )
    g = EarthGrid(tile_size=tile_size)
    x0, z_south = lonlat_to_block(west, south, g)
    x1, z_north = lonlat_to_block(east, north, g)
    tx0 = min(x0, x1) // tile_size
    tx1 = max(x0, x1) // tile_size
    tz0 = min(z_north, z_south) // tile_size
    tz1 = max(z_north, z_south) // tile_size
    return [(tx, tz) for tz in range(tz0, tz1 + 1) for tx in range(tx0, tx1 + 1)]
