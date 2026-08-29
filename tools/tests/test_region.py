import json
import unicodedata
from pathlib import Path

import pytest

from realearth.region import build_region
from realearth.settlements import decode_poi_blob
from realearth.tile_format import read_manifest, read_tile, tile_path


def test_build_synthetic_region(tmp_path: Path):
    m = build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        tmp_path,
        resolution_m=120.0,
        source="synthetic",
        name="Test",
        max_dim=256,
    )
    assert m.world_width > 0
    assert (tmp_path / "earth.manifest.json").exists()
    assert (tmp_path / "export_7dtd" / "heightmap.png").exists()
    assert (tmp_path / "export_7dtd" / "preview.png").exists()
    man = read_manifest(tmp_path / "earth.manifest.json")
    assert len(man.tiles) >= 1
    t0 = man.tiles[0]
    tile = read_tile(tile_path(tmp_path, t0["tx"], t0["tz"]))
    assert tile.elevation_m.shape[0] == 512


def test_build_region_settlements_json_utf8_nfc(tmp_path: Path):
    """Names survive the storage boundary: NFC form, real UTF-8 bytes, no \\u escapes."""
    nfd_name = unicodedata.normalize("NFD", "São Paulo")
    gj = tmp_path / "s.geojson"
    gj.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-46.6, -23.55]},
                        "properties": {"name": nfd_name, "population": 12_000_000},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    from realearth.settlements import load_settlements_geojson

    build_region(
        -47.0,
        -24.2,
        -46.0,
        -23.0,
        tmp_path,
        resolution_m=200.0,
        source="synthetic",
        name="Utf8Test",
        max_dim=128,
        settlements=load_settlements_geojson(gj),
        also_export_7dtd=False,
    )
    raw = (tmp_path / "settlements.json").read_bytes()
    assert "São Paulo".encode() in raw
    rows = json.loads(raw.decode("utf-8"))
    names = [r["name"] for r in rows]
    assert names.count("São Paulo") == 1


def test_region_tile_pois_stamp_each_place_once(tmp_path: Path):
    """A density core snapped to a settlement name is the same place: the tile
    POI plan must not stamp it twice (Denver sits mid-bbox for seed cities)."""
    m = build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        tmp_path,
        resolution_m=120.0,
        source="synthetic",
        name="PoiDedupe",
        max_dim=256,
    )
    names = []
    for t in m.tiles:
        tile = read_tile(tile_path(tmp_path, t["tx"], t["tz"]))
        names.extend(p["name"] for p in decode_poi_blob(tile.poi_blob))
    assert names.count("Denver") == 1


def test_build_region_gebco_bathymetry_negative_flow(tmp_path: Path):
    """source=gebco: a negative-elevation (below-sea) GeoTIFF must flow through
    the pipeline unchanged into .rte tiles and map to real diggable game Y at
    the product sea anchor (not clamped to 1). Uses a synthetic trench raster;
    the real GEBCO dataset is the same GeoTIFF shape."""
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_origin

    size = 64
    yy, xx = np.mgrid[0:size, 0:size]
    dist = np.sqrt((xx - size / 2) ** 2 + (yy - size / 2) ** 2) / (size / 2)
    elev = (-200.0 - 9800.0 * np.exp(-((dist / 0.35) ** 2))).astype(np.float32)
    tif = tmp_path / "bathy.tif"
    with rasterio.open(
        tif,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(142.0, 11.0, 1.0 / size, 1.0 / size),
    ) as ds:
        ds.write(elev, 1)

    m = build_region(
        142.0,
        10.0,
        143.0,
        11.0,
        tmp_path / "pack",
        resolution_m=4000.0,
        source="gebco",
        geotiff=tif,
        name="Trench",
        max_dim=128,
    )
    assert "GEBCO" in m.sources[0]
    tile = read_tile(tile_path(tmp_path / "pack", m.tiles[0]["tx"], m.tiles[0]["tz"]))
    assert float(tile.elevation_m.min()) < -5000  # deep floor survived .rte
    # product mapping at the 16000 sea anchor: floor lands in the diggable band
    from realearth import DEFAULT_SEA_LEVEL_GAME_Y, ENGINE_TARGET_MAX_Y
    from realearth.height import compress_elevation

    y = compress_elevation(
        tile.elevation_m,
        sea_level_y=DEFAULT_SEA_LEVEL_GAME_Y,
        max_y=ENGINE_TARGET_MAX_Y,
        profile="one_to_one",
        regional_exaggeration=1.0,
    )
    assert int(y.min()) > 0 and int(y.min()) < 10000  # not clamped to 1
    assert int(y.max()) < DEFAULT_SEA_LEVEL_GAME_Y  # whole pack below sea
