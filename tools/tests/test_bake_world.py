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
    assert result["pre_bake_snapshot"] is None


def test_bake_world_snapshots_previous_output(tmp_path: Path):
    """A rebake must move the previous world aside, never overwrite in place."""
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
    bake_world_from_pack(pack, out, size=2048, name="BakeTest")
    sentinel = out / "heightmap.png"
    first_bytes = sentinel.read_bytes()

    result = bake_world_from_pack(pack, out, size=2048, name="BakeTest")
    aside = Path(result["pre_bake_snapshot"])  # type: ignore[arg-type]
    assert aside.is_dir()
    assert aside.name.startswith("world.pre-bake-")
    # every previous byte survives under the snapshot, untouched by the rebake
    assert (aside / "heightmap.png").read_bytes() == first_bytes
    # fresh output was written alongside it
    assert (out / "heightmap.png").exists()
    assert (out / "heightmap.png").stat().st_size > 0
