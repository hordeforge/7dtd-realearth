"""Corridor stamping: deterministic road/river/rail rules."""

import json

import numpy as np
import pytest

from realearth.corridors import CorridorLayer, load_corridors, stamp_corridors
from realearth.landcover import LandCover


def _fc(*features: dict) -> str:
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def _line(kind: str, *coords: tuple[float, float]) -> dict:
    return {
        "type": "Feature",
        "properties": {"kind": kind},
        "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
    }


def test_load_corridors_splits_kinds(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(
        _fc(
            _line("river", (-105.0, 39.6), (-105.0, 39.9)),
            _line("road", (-105.2, 39.75), (-104.9, 39.75)),
        ),
        encoding="utf-8",
    )
    layers = load_corridors(p)
    by_kind = {layer.kind: layer for layer in layers}
    assert set(by_kind) == {"road", "river", "rail"}
    assert len(by_kind["road"].segments) == 1
    assert len(by_kind["river"].segments) == 1


def test_load_corridors_rejects_malformed(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(
        _fc(
            {
                "type": "Feature",
                "properties": {"kind": "road"},
                "geometry": {"type": "Point", "coordinates": [1, 2]},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="LineString"):
        load_corridors(p)


def test_road_beats_river_at_bridge():
    """Road crosses a river: the crossing cell is URBAN with zero population
    (bridge semantics), river-only cells stay INLAND_WATER."""
    layers = [
        CorridorLayer((((-105.0, 39.6), (-105.0, 39.9)),), "river"),
        CorridorLayer((((-105.2, 39.75), (-104.9, 39.75)),), "road"),
    ]
    lc = np.full((40, 40), LandCover.GRASS, dtype=np.uint8)
    pop = np.full((40, 40), 50, dtype=np.uint8)
    stamp_corridors(lc, pop, layers, west=-105.2, north=39.9, per_lon=100.0, per_lat=100.0)
    # river column x=20 (lon -105.0); road row y=15 (lat 39.75)
    assert LandCover(lc[15, 20]) == LandCover.URBAN  # bridge: road wins
    assert int(pop[15, 20]) == 0
    assert LandCover(lc[5, 20]) == LandCover.INLAND_WATER  # river only
    assert int(pop[5, 20]) == 50  # riverside population kept
    assert LandCover(lc[15, 25]) == LandCover.URBAN  # road only
    assert int(pop[15, 25]) == 0


def test_road_never_paints_open_ocean():
    """Rule 2: a road over the ocean (ferry route) must not become URBAN land."""
    layers = [CorridorLayer((((0.0, 0.0), (1.0, 0.0)),), "road")]
    lc = np.full((20, 20), LandCover.OCEAN, dtype=np.uint8)
    pop = np.full((20, 20), 0, dtype=np.uint8)
    stamp_corridors(lc, pop, layers, west=0.0, north=1.0, per_lon=10.0, per_lat=10.0)
    assert (lc == LandCover.OCEAN).all()  # ocean untouched


def test_stamping_is_idempotent():
    """Re-stamping the same corridors yields the same result (deterministic)."""
    layers = [CorridorLayer((((0.0, 0.5), (1.0, 0.5)),), "river")]
    lc1 = np.full((20, 20), LandCover.GRASS, dtype=np.uint8)
    pop1 = np.full((20, 20), 10, dtype=np.uint8)
    stamp_corridors(lc1, pop1, layers, west=0.0, north=1.0, per_lon=10.0, per_lat=10.0)
    stamp_corridors(lc1, pop1, layers, west=0.0, north=1.0, per_lon=10.0, per_lat=10.0)
    lc2 = np.full((20, 20), LandCover.GRASS, dtype=np.uint8)
    pop2 = np.full((20, 20), 10, dtype=np.uint8)
    stamp_corridors(lc2, pop2, layers, west=0.0, north=1.0, per_lon=10.0, per_lat=10.0)
    assert (lc1 == lc2).all() and (pop1 == pop2).all()


def test_build_region_with_corridors(tmp_path):
    """End to end: build-region accepts a corridor GeoJSON, records it in the
    sources, and runs the deterministic stamp (no crash, landcover preserved
    where rules say so: ocean stays ocean)."""
    from realearth.region import build_region
    from realearth.tile_format import read_manifest, read_tile, tile_path

    p = tmp_path / "c.json"
    p.write_text(
        _fc(_line("river", (-105.0, 39.6), (-105.0, 39.9))),
        encoding="utf-8",
    )
    plain = tmp_path / "plain"
    build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        plain,
        resolution_m=250.0,
        source="synthetic",
        name="Plain",
        max_dim=64,
        also_export_7dtd=False,
    )
    corr = tmp_path / "corr"
    build_region(
        -105.2,
        39.6,
        -104.9,
        39.9,
        corr,
        resolution_m=250.0,
        source="synthetic",
        name="Corr",
        max_dim=64,
        corridors=p,
        also_export_7dtd=False,
    )
    man = read_manifest(corr / "earth.manifest.json")
    assert any("Corridors" in s for s in man.sources)
    tile = read_tile(tile_path(corr, 0, 0))
    assert tile.landcover is not None
    # Rules hold on the degenerate synthetic terrain (mostly ocean/urban):
    # ocean cells are never painted (rule 2), so no INLAND_WATER appears where
    # the river only crosses ocean/urban, and the pack still loads.
    plain_tile = read_tile(tile_path(plain, 0, 0))
    assert plain_tile.landcover.shape == tile.landcover.shape
    ocean_plain = (plain_tile.landcover == int(LandCover.OCEAN)).sum()
    ocean_corr = (tile.landcover == int(LandCover.OCEAN)).sum()
    assert ocean_corr >= ocean_plain  # ocean never shrinks
