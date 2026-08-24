"""Continuous travel: wrap, local↔absolute, origin slide (shipped local_window)."""

from realearth.coords import EarthGrid, block_to_lonlat, lonlat_to_block
from realearth.local_window import LocalWindow


def test_local_absolute_roundtrip_center():
    g = EarthGrid()
    win = LocalWindow(grid=g, size=1024, enable_longitude_wrap=True)
    ex, ez = lonlat_to_block(-104.99, 39.74, g)
    win.center_on_absolute(ex, ez)
    half = win.size // 2
    # center local maps near absolute
    ax, az = win.local_to_earth(half, half)
    assert abs(ax - ex) <= 1
    assert abs(az - ez) <= 1
    lx, lz = win.earth_to_local(ex, ez)
    assert abs(lx - half) <= 1
    assert abs(lz - half) <= 1


def test_antimeridian_wrap_in_window():
    g = EarthGrid()
    win = LocalWindow(grid=g, size=1024, enable_longitude_wrap=True)
    # center near wrap edge (x ≈ 0)
    win.center_on_absolute(100, g.height // 2)
    # local that goes west of origin should wrap
    ax, az = win.local_to_earth(-50, win.size // 2)
    assert 0 <= ax < g.width
    # far east absolute near width-1
    win.center_on_absolute(g.width - 50, g.height // 2)
    ax2, _ = win.local_to_earth(win.size // 2, win.size // 2)
    assert ax2 >= g.width - 200 or ax2 < 200  # near wrap


def test_origin_slide_recenters_when_near_edge():
    g = EarthGrid()
    win = LocalWindow(grid=g, size=1024, enable_longitude_wrap=True)
    ex, ez = 5_000_000, 8_000_000
    win.center_on_absolute(ex, ez)
    origin_before = (win.origin_x, win.origin_z)
    # walk to far edge of host
    edge_x = win.size - 8
    edge_z = win.size // 2
    abs_at_edge = win.local_to_earth(edge_x, edge_z)
    slid, nx, nz, ax, az = win.tick_player_local(edge_x, edge_z, allow_slide=True)
    assert slid is True
    assert (win.origin_x, win.origin_z) != origin_before
    # absolute Earth position is preserved across the slide
    assert (ax, az) == abs_at_edge
    assert 1 <= nx <= win.size - 2
    assert 1 <= nz <= win.size - 2
    # round-trip: absolute still maps consistently
    lx2, lz2 = win.earth_to_local(ax, az)
    assert abs(lx2 - nx) <= 2
    assert abs(lz2 - nz) <= 2


def test_no_slide_when_shared_fixed():
    g = EarthGrid()
    win = LocalWindow(grid=g, size=512, enable_longitude_wrap=True)
    win.center_on_absolute(1000, 2000)
    origin = (win.origin_x, win.origin_z)
    slid, nx, nz, ax, az = win.tick_player_local(win.size - 5, 10, allow_slide=False)
    assert slid is False
    assert (win.origin_x, win.origin_z) == origin
    assert nx == win.size - 5


def test_wrap_x_full_earth_identity():
    g = EarthGrid()
    assert g.wrap_x(g.width) == 0
    assert g.wrap_x(-1) == g.width - 1
    x, z = lonlat_to_block(179.9, 0.0, g)
    lon, lat = block_to_lonlat(x, z, g)
    assert abs(lon - 179.9) < 0.05
    assert abs(lat) < 0.05


def test_wrapped_delta_antimeridian_slide():
    """Origin slide across the seam reports a short forward delta (entity remap contract)."""
    from realearth.local_window import wrapped_delta

    g = EarthGrid()
    # Slide from origin 40,074,000 to 200: absolute moved +1217 through the seam,
    # not -40,073,800. Entity remap shifts locals by exactly this delta.
    assert wrapped_delta(200 - 40_074_000, g.width) == 1_217
    # Small non-seam deltas pass through unchanged.
    assert wrapped_delta(512, g.width) == 512
    assert wrapped_delta(-512, g.width) == -512
    # Degenerate extent stays safe.
    assert wrapped_delta(-7, 0) == 0
