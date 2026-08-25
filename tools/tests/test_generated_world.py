"""Drive shipped GeneratedWorld bake path and verify DTM layout/sizes."""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from realearth import DEFAULT_SEA_LEVEL_GAME_Y
from realearth.generated_world import bake_generated_world, game_y_to_dtm_u16, write_map_info
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
    # Deterministic tiny template: write_main_ttw only byte-copies the template
    # (or splices a version string into ttw-magic data), so a fixed synthetic
    # blob keeps CI identical to dev machines with a 7DTD install.
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


def test_write_map_info_escapes_hostile_name(tmp_path: Path):
    """A world name with XML metacharacters must not break map_info.xml."""
    hostile = 'Rocks & Co <test> "quoted"'
    p = tmp_path / "map_info.xml"
    write_map_info(p, 2048, hostile, game_version="V.3.0.1")
    root = ET.parse(p).getroot()
    props = {e.get("name"): e.get("value") for e in root.findall("property")}
    assert props["Description"] == f"RealEarth continuous single map: {hostile}"


def test_population_byte_roundtrip_bands():
    """Decoded density bytes must land in the same band the encoder saw.

    bake_generated_world inverts settlements.population_to_byte (50*log10(p+1))
    so detect_city_cores re-bands cores identically to the streamed path. The
    old linear proxy (byte*80) read a ~1500 people/km2 town (byte 159) as 12720,
    i.e. large_city instead of town.
    """
    from realearth.density import density_to_band
    from realearth.settlements import population_to_byte

    for people_km2, want_band in [
        (1500.0, "town"),
        (5000.0, "large_city"),
        (15000.0, "metro"),
        # Not exactly 80: one byte of quantization is ~2% there, so a value on
        # the exact band boundary can decode just below it.
        (100.0, "hamlet"),
    ]:
        byte = int(population_to_byte(np.array([people_km2]))[0])
        decoded = 10.0 ** (byte / 50.0) - 1.0
        assert density_to_band(decoded) == want_band
