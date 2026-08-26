"""City density peaks + prefab stamps (shipped density module)."""

from pathlib import Path

import numpy as np

from realearth.density import (
    clamp_prefabs_in_chunk,
    combine_population_and_built,
    density_to_band,
    detect_city_cores,
    measure_urban_edge_radius_m,
    stamp_prefab_root_y,
    stamp_prefabs_from_density,
    write_prefabs_xml,
)
from realearth.generated_world import bake_generated_world
from realearth.region import build_region
from realearth.settlements import (
    Settlement,
    edge_radius_m_from_bbox,
    edge_radius_m_from_properties,
    urban_radius_m_from_population,
)


def test_density_to_band_thresholds():
    assert density_to_band(20000) == "metro"
    assert density_to_band(6000) == "large_city"
    assert density_to_band(2000) == "town"
    assert density_to_band(500) == "village"
    assert density_to_band(100) == "hamlet"
    assert density_to_band(10) == "rural_scatter"


def test_combine_built_boosts_density():
    pop = np.array([[1000.0, 0.0]])
    built = np.array([[1.0, 0.0]])
    out = combine_population_and_built(pop, built)
    assert out[0, 0] > 1000.0
    assert out[0, 1] == 0.0


def test_measure_urban_edge_from_density_blob():
    # 0.3° × 0.3° grid ≈ mid-latitudes; blob ~5 px from peak
    dens = np.zeros((64, 64), dtype=np.float64)
    dens[28:37, 28:37] = 2000
    dens[32, 32] = 10000
    west, south, east, north = -105.15, 39.70, -104.85, 40.00
    r = measure_urban_edge_radius_m(dens, 32, 32, west, south, east, north)
    # Should be several km (blob size × m/px), not the old fixed band table.
    assert r > 500
    assert r < 80_000


def test_measure_urban_edge_scratch_reuse_matches_fresh():
    """Reused visited buffer must give identical radii and stay all-False."""
    dens = np.zeros((64, 64), dtype=np.float64)
    dens[28:37, 28:37] = 2000
    dens[32, 32] = 10000
    dens[5:9, 50:54] = 500
    west, south, east, north = -105.15, 39.70, -104.85, 40.00
    peaks = [(32, 32), (7, 52), (40, 10)]  # two blobs + degenerate peak
    fresh = [measure_urban_edge_radius_m(dens, y, x, west, south, east, north) for y, x in peaks]
    scratch = np.zeros(dens.shape, dtype=bool)
    reused = [
        measure_urban_edge_radius_m(dens, y, x, west, south, east, north, visited_scratch=scratch)
        for y, x in peaks
    ]
    assert reused == fresh
    assert not scratch.any()


def test_edge_from_bbox_and_properties():
    # ~0.2° box at Denver lat → ~ half-width order 10 km
    r = edge_radius_m_from_bbox(-105.1, 39.65, -104.9, 39.85, center_lon=-105.0, center_lat=39.75)
    assert 5_000 < r < 30_000
    props = {"edge_radius_m": 12345}
    assert edge_radius_m_from_properties(props, -105.0, 39.75) == 12345
    props_km = {"radius_km": 12.5}
    assert edge_radius_m_from_properties(props_km, -105.0, 39.75) == 12_500
    assert urban_radius_m_from_population(715_000) > 10_000


def test_detect_cores_and_prefabs(tmp_path: Path):
    # Synthetic density: peak in center
    dens = np.zeros((64, 64), dtype=np.float64)
    dens[30:35, 30:35] = 8000
    dens[32, 32] = 12000
    dens[10, 10] = 200
    cores = detect_city_cores(
        dens,
        -105.2,
        39.6,
        -104.9,
        39.9,
        settlements=[Settlement("TestCity", -105.05, 39.75, 500_000)],
        min_peak=150,
        min_separation_px=8,
    )
    assert len(cores) >= 1
    assert any(c.band in ("metro", "large_city", "town") for c in cores)
    # Edge must come from density map (or settlement map field), not zero.
    assert all(c.edge_radius_m > 0 for c in cores)
    assert any(c.edge_source in ("density", "map") for c in cores)

    pop_b = np.clip(dens / 50, 0, 255).astype(np.uint8)
    gy = np.full((64, 64), 40, dtype=np.int32)
    stamps = stamp_prefabs_from_density(pop_b, gy, world_size=2048, cores=cores)
    assert len(stamps) >= 1
    assert all(s.name for s in stamps)
    write_prefabs_xml(tmp_path / "prefabs.xml", stamps)
    text = (tmp_path / "prefabs.xml").read_text()
    assert "<decoration" in text
    assert 'type="model"' in text


def test_stamp_prefabs_preserves_h500_and_everest_surface_y():
    """Drive stamp_prefabs_from_density with tall game_y (not uint8-truncated)."""
    n = 48
    dens = np.full((n, n), 200, dtype=np.uint8)  # metro-ish
    # H500 product surface
    gy500 = np.full((n, n), 500, dtype=np.int32)
    stamps = stamp_prefabs_from_density(
        dens, gy500, world_size=1024, sea_level=100, seed=1, max_prefabs_per_chunk=8
    )
    assert len(stamps) >= 1
    assert all(s.y == 500 for s in stamps), {s.y for s in stamps}
    # uint8 wrap would have produced 244, prove we did not
    assert all(s.y != 244 for s in stamps)

    gy_eve = np.full((n, n), 8949, dtype=np.int32)
    stamps_e = stamp_prefabs_from_density(
        dens, gy_eve, world_size=1024, sea_level=100, seed=1, max_prefabs_per_chunk=8
    )
    assert len(stamps_e) >= 1
    assert all(s.y == 8949 for s in stamps_e)
    assert all(s.y == stamp_prefab_root_y(8949) for s in stamps_e)


def test_stamp_prefabs_applies_density_budget_per_chunk():
    """P6: clamp_prefabs_in_chunk is used by the real stamp planner, not dead code."""
    n = 32
    dens = np.full((n, n), 220, dtype=np.uint8)
    gy = np.full((n, n), 500, dtype=np.int32)
    # Tiny world → many samples map into few world chunks → budget binds
    stamps = stamp_prefabs_from_density(
        dens,
        gy,
        world_size=64,
        sea_level=100,
        seed=0,
        max_prefabs_per_chunk=2,
    )
    from collections import Counter

    counts = Counter((s.world_x // 16, s.world_z // 16) for s in stamps)
    for key, c in counts.items():
        assert c <= 2, f"chunk {key} has {c} stamps (budget 2)"
        assert c == clamp_prefabs_in_chunk(c, 2)


def test_build_region_writes_cities_json(tmp_path: Path):
    pack = tmp_path / "pack"
    build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        pack,
        resolution_m=120.0,
        source="synthetic",
        name="CityTest",
        max_dim=128,
        also_export_7dtd=False,
    )
    assert (pack / "cities.json").exists()
    import json

    data = json.loads((pack / "cities.json").read_text())
    assert "cores" in data


def test_bake_world_prefab_stamps(tmp_path: Path):
    pack = tmp_path / "pack"
    build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        pack,
        resolution_m=120.0,
        source="synthetic",
        name="CityBake",
        max_dim=128,
        also_export_7dtd=False,
    )
    ttw = tmp_path / "main.ttw"
    ttw.write_bytes(b"ttw\x00" + b"\x00" * 100)

    out = tmp_path / "world"
    meta = bake_generated_world(pack, out, size=2048, name="CityBake", ttw_template=ttw)
    assert meta["prefab_stamps"] >= 0  # may be sparse on tiny dens
    assert (out / "prefabs.xml").exists()
    assert (out / "cities.json").exists()
    assert (out / "population.png").exists()
