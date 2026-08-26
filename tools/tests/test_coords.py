from realearth.coords import EarthGrid, block_to_lonlat, block_to_tile, lonlat_to_block


def test_equator_prime_meridian():
    x, z = lonlat_to_block(0.0, 0.0)
    lon, lat = block_to_lonlat(x, z)
    assert abs(lon) < 0.01
    assert abs(lat) < 0.01


def test_wrap_x():
    g = EarthGrid()
    assert g.wrap_x(g.width) == 0
    assert g.wrap_x(-1) == g.width - 1


def test_nyc_in_northern_hemisphere():
    x, z = lonlat_to_block(-74.006, 40.7128)
    lon, lat = block_to_lonlat(x, z)
    assert lat > 40.0
    assert -75 < lon < -73
    tx, tz = block_to_tile(x, z)
    assert tx >= 0 and tz >= 0


def test_out_of_range_lon_folds_o1():
    # Contract shared by tools/realearth/coords.py and EarthCoords.LonLatToBlock:
    # any finite lon folds into [-180, 180) and maps to the same block as its
    # wrapped value. The C# side must do this in O(1) (no per-360 decrement loop):
    # a config typo like SpawnLongitude=1120000000000 froze the game thread there.
    for raw in (
        540.0,
        721.0,
        -190.0,
        -540.0,
        200.0,
        -200.0,
        1_120_000_000_000.0,  # the actual SpawnLongitude typo from the incident
        -1_120_000_000_000.0,
        180.0,  # half-open seam: must land on -180's block, not width
    ):
        x_raw, _ = lonlat_to_block(raw, 0.0)
        x_wrapped, _ = lonlat_to_block(((raw + 180.0) % 360.0) - 180.0, 0.0)
        assert x_raw == x_wrapped
