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
