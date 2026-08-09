from pathlib import Path

from realearth.region import build_region
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
