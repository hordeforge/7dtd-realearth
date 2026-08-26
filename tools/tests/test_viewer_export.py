import json
from pathlib import Path

import pytest

from realearth.region import build_region
from realearth.tile_format import read_manifest, tile_path
from realearth.viewer_export import export_viewer_pack, mosaic_pack


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


def _tiny_region(tmp_path: Path) -> Path:
    pack = tmp_path / "pack"
    build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        pack,
        resolution_m=250.0,
        tile_size=32,
        source="synthetic",
        name="Tiny",
        max_dim=64,
        also_export_7dtd=False,
    )
    man = read_manifest(pack / "earth.manifest.json")
    assert len(man.tiles) >= 2
    return pack


def test_mosaic_pack_warns_on_missing_tile(tmp_path: Path, capsys):
    """A deleted manifest tile must not silently become ocean in baked output."""
    pack = _tiny_region(tmp_path)
    man = read_manifest(pack / "earth.manifest.json")
    tx, tz = man.tiles[0]["tx"], man.tiles[0]["tz"]
    tile_path(pack, tx, tz).unlink()

    data = mosaic_pack(pack)
    assert data.elevation.size > 0
    err = capsys.readouterr().err
    assert "missing" in err
    assert f"({tx},{tz})" in err


def test_mosaic_pack_still_raises_when_all_tiles_missing(tmp_path: Path):
    pack = _tiny_region(tmp_path)
    man = read_manifest(pack / "earth.manifest.json")
    for t in man.tiles:
        tile_path(pack, t["tx"], t["tz"]).unlink()
    with pytest.raises(FileNotFoundError):
        mosaic_pack(pack)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tile_size", 0),
        ("tile_size", 100000),
        ("world_width", -1),
        ("world_height", -1),
    ],
)
def test_mosaic_pack_rejects_hostile_manifest_dims(
    tmp_path: Path, field: str, value: int
):
    """Manifest integers must not steer np.full into an unbounded allocation."""
    pack = _tiny_region(tmp_path)
    raw = json.loads((pack / "earth.manifest.json").read_text(encoding="utf-8"))
    raw[field] = value
    (pack / "earth.manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        mosaic_pack(pack)


def test_mosaic_pack_rejects_oversized_tile_grid(tmp_path: Path):
    """A manifest claiming a huge tile grid must fail loudly, not OOM."""
    pack = _tiny_region(tmp_path)
    raw = json.loads((pack / "earth.manifest.json").read_text(encoding="utf-8"))
    raw["tiles"] = [{"tx": 0, "tz": 0}, {"tx": 100000, "tz": 100000}]
    (pack / "earth.manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="cap is"):
        mosaic_pack(pack)
