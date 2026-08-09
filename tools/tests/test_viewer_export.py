from pathlib import Path

from realearth.region import build_region
from realearth.viewer_export import export_viewer_pack


def test_export_viewer(tmp_path: Path):
    pack = tmp_path / "pack"
    build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        pack,
        resolution_m=120.0,
        source="synthetic",
        name="ViewTest",
        max_dim=128,
        also_export_7dtd=False,
    )
    out = tmp_path / "viewer_out"
    export_viewer_pack(pack, out, max_dim=256, name="ViewTest")
    assert (out / "viewer.json").exists()
    assert (out / "hybrid.png").exists()
    assert (out / "elevation.png").exists()
    assert (out / "landcover.png").exists()
    assert (out / "population.png").exists()
