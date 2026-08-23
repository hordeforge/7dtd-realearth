import json
import unicodedata
from pathlib import Path

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
