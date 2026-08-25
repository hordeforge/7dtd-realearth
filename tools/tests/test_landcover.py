"""Landcover heuristics: elevation/latitude classes + biome RGB painting."""

import numpy as np

from realearth.landcover import (
    BIOME_RGB,
    LandCover,
    classify_from_elevation_and_lat,
    landcover_to_biome_rgb,
)


def _classify(elev_m: float, lat_deg: float) -> np.ndarray:
    """Classify one cell under a uniform latitude field."""
    return classify_from_elevation_and_lat(
        np.array([[elev_m]], dtype=np.float64),
        np.array([[lat_deg]], dtype=np.float64),
    )


def test_ocean_covers_all_nonpositive_elevation():
    lc = classify_from_elevation_and_lat(
        np.array([[-1.0, 0.0]]), np.array([[65.0, 0.0]])
    )
    assert (lc == int(LandCover.OCEAN)).all()


def test_polar_land_is_snow():
    assert (_classify(100.0, 61.0)[0, 0]) == int(LandCover.SNOW)


def test_equatorial_high_peak_is_snow():
    assert (_classify(4000.0, 0.0)[0, 0]) == int(LandCover.SNOW)


def test_midlatitude_lowland_is_forest():
    assert (_classify(500.0, 45.0)[0, 0]) == int(LandCover.FOREST)


def test_desert_belt_needs_low_elevation_and_mid_latitude():
    assert (_classify(200.0, 25.0)[0, 0]) == int(LandCover.DESERT)
    # Near-equator lowlands stay forest (wet tropics guess), not desert.
    assert (_classify(200.0, 5.0)[0, 0]) == int(LandCover.FOREST)
    # Inside the belt but above the snow line: snow wins over desert.
    assert (_classify(4000.0, 25.0)[0, 0]) == int(LandCover.SNOW)


def test_high_lowlatitude_land_is_barren():
    # Above the forest ceiling but below every snow trigger at low latitude.
    assert (_classify(3000.0, 10.0)[0, 0]) == int(LandCover.BARREN)


def test_urban_mask_only_applies_to_land():
    elev = np.array([[-5.0, 100.0]])
    lat = np.array([[45.0, 45.0]])
    lc = classify_from_elevation_and_lat(
        elev, lat, urban_mask=np.array([[True, True]])
    )
    assert int(lc[0, 0]) == int(LandCover.OCEAN)
    assert int(lc[0, 1]) == int(LandCover.URBAN)


def test_biome_rgb_paints_every_known_code_with_its_color():
    members = list(LandCover)
    codes = np.array([[int(c) for c in members]], dtype=np.uint8)
    rgb = landcover_to_biome_rgb(codes)
    assert rgb.shape == (1, len(members), 3)
    for col, cover in enumerate(members):
        assert rgb[0, col].tolist() == list(BIOME_RGB[cover]), cover
