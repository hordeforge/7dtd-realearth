from pathlib import Path

from realearth.bake_world import bake_world_from_pack, snap_world_size
from realearth.region import build_region


def test_snap_world_size():
    assert snap_world_size(8000) == 8192
    assert snap_world_size(16384) == 16384
    assert snap_world_size(100) == 2048


def test_bake_world(tmp_path: Path):
    pack = tmp_path / "pack"
    build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        pack,
        resolution_m=120.0,
        source="synthetic",
        name="BakeTest",
        max_dim=128,
        also_export_7dtd=False,
    )
    out = tmp_path / "world"
    result = bake_world_from_pack(pack, out, size=2048, name="BakeTest")
    assert result["size"] == 2048
    assert (out / "heightmap.png").exists()
    assert (out / "biomes.png").exists()
    assert (out / "map_info.json").exists()
    assert (out / "README_INSTALL.txt").exists()
