"""Drive shipped GeneratedWorld bake path and verify DTM layout/sizes."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from realearth import DEFAULT_SEA_LEVEL_GAME_Y
from realearth.generated_world import bake_generated_world, game_y_to_dtm_u16
from realearth.region import build_region


def test_game_y_to_dtm_u16_scale():
    # Verified against V1.0 sample world: game height ≈ u16 / 256
    sea = DEFAULT_SEA_LEVEL_GAME_Y
    y = np.array([[sea, 61], [1, 250]], dtype=np.uint8)
    u = game_y_to_dtm_u16(y)
    assert int(u[0, 0]) == sea * 256
    assert int(u[0, 1]) == 61 * 256
    assert int(u[1, 0]) == 1 * 256
    assert int(u[1, 1]) == 250 * 256


def test_bake_generated_world_files_and_dtm_size(tmp_path: Path):
    pack = tmp_path / "pack"
    build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        pack,
        resolution_m=120.0,
        source="synthetic",
        name="GenWorldTest",
        max_dim=128,
        also_export_7dtd=False,
    )
    # Need a main.ttw template — copy minimal from sample if present
    sample_ttw = Path.home() / ".local/share/7DaysToDie/GeneratedWorlds"
    ttw = None
    if sample_ttw.is_dir():
        for p in sample_ttw.glob("*/main.ttw"):
            ttw = p
            break
    if ttw is None:
        # create tiny dummy so bake can proceed in CI without game data
        ttw = tmp_path / "main.ttw"
        ttw.write_bytes(b"ttw\x00" + b"\x00" * 100)

    out = tmp_path / "RealEarthTest"
    size = 2048
    meta = bake_generated_world(
        pack,
        out,
        size=size,
        name="RealEarthTest",
        ttw_template=ttw,
    )
    assert meta["size"] == size
    assert meta["dtm_bytes"] == size * size * 2

    required = [
        "dtm.raw",
        "dtm_processed.raw",
        "biomes.png",
        "map_info.xml",
        "spawnpoints.xml",
        "prefabs.xml",
        "radiation.png",
        "splat3.png",
        "splat4.png",
        "splat3_half.png",
        "splat4_half.png",
        "splat3_processed.png",
        "splat4_processed.png",
        "main.ttw",
        "checksums.txt",
    ]
    for name in required:
        assert (out / name).exists(), name

    dtm = (out / "dtm.raw").read_bytes()
    assert len(dtm) == size * size * 2
    # little-endian u16, sea-ish values near sea*256
    vals = [struct.unpack_from("<H", dtm, i * 2)[0] for i in range(0, 1000, 50)]
    assert all(0 < v < 65535 for v in vals)
    assert any(v >= 256 for v in vals)

    text = (out / "map_info.xml").read_text(encoding="utf-8")
    assert f'HeightMapSize" value="{size},{size}"' in text or f"{size},{size}" in text

    sp = (out / "spawnpoints.xml").read_text(encoding="utf-8")
    assert "<spawnpoint" in sp
