"""Multiplayer origin modes, full-Earth coords, host fold, tile bubbles."""

from realearth.coords import EarthGrid, block_to_lonlat, lonlat_to_block
from realearth.local_window import (
    LocalWindow,
    fold_x,
    fold_z,
    multi_player_hot_tiles,
    stream_tile_bubble,
    tiles_to_evict,
)


def test_full_earth_lonlat_roundtrip_equator():
    g = EarthGrid()
    for lon in (-179.9, -90.0, 0.0, 90.0, 179.9):
        x, z = lonlat_to_block(lon, 0.0, g)
        lon2, lat2 = block_to_lonlat(x, z, g)
        assert abs(lon2 - lon) < 0.05
        assert abs(lat2) < 0.05
        assert 0 <= x < g.width
        assert 0 <= z < g.height


def test_full_earth_wrap_x():
    g = EarthGrid()
    assert g.wrap_x(g.width) == 0
    assert g.wrap_x(-1) == g.width - 1
    assert g.wrap_x(g.width * 3 + 5) == 5


def test_shared_fixed_never_slides():
    g = EarthGrid(width=40_075_017, height=20_003_931, tile_size=512)
    win = LocalWindow(
        grid=g,
        size=2048,
        enable_longitude_wrap=True,
        multiplayer_origin_mode="SharedFixed",
    )
    win.center_on_absolute(5_000_000, 8_000_000)
    origin = (win.origin_x, win.origin_z)
    slid, nx, nz, ax, az = win.tick_player_local(win.size - 5, 10)
    assert slid is False
    assert (win.origin_x, win.origin_z) == origin
    assert nx == win.size - 5


def test_solo_slide_recenters_near_edge():
    g = EarthGrid()
    win = LocalWindow(
        grid=g,
        size=1024,
        enable_longitude_wrap=True,
        multiplayer_origin_mode="SoloSlide",
    )
    win.center_on_absolute(1_000_000, 2_000_000)
    origin_before = (win.origin_x, win.origin_z)
    slid, nx, nz, ax, az = win.tick_player_local(win.size - 5, win.size // 2)
    assert slid is True
    assert (win.origin_x, win.origin_z) != origin_before
    assert 1 <= nx <= win.size - 2


def test_shared_slide_blocks_when_multiplayer():
    g = EarthGrid()
    win = LocalWindow(
        grid=g,
        size=1024,
        multiplayer_origin_mode="SharedSlide",
        player_count=3,
        enable_longitude_wrap=True,
    )
    win.center_on_absolute(1000, 2000)
    origin = (win.origin_x, win.origin_z)
    slid, *_ = win.tick_player_local(win.size - 5, 10)
    assert slid is False
    assert (win.origin_x, win.origin_z) == origin
    win.player_count = 1
    slid2, *_ = win.tick_player_local(win.size - 5, 10)
    assert slid2 is True


def test_host_fold_pack_peak_reachable():
    """Regional pack 512: host chunk 2048*16 folds into pack."""
    pack = EarthGrid(width=512, height=512, tile_size=512)
    win = LocalWindow(
        grid=pack,
        size=512,
        enable_longitude_wrap=False,
        fold_host_into_pack=True,
        multiplayer_origin_mode="SharedFixed",
    )
    win.set_origin(0, 0)
    # engine local at host far away
    ex, ez = win.local_to_earth(2048 * 16, 2048 * 16)
    assert ex == fold_x(2048 * 16, 512)
    assert ez == fold_z(2048 * 16, 512)
    # pack center from any tiled host offset
    for k in range(5):
        host = 256 + k * 512
        ex2, ez2 = win.local_to_earth(host, host)
        assert ex2 == 256
        assert ez2 == 256


def test_stream_bubbles_overlap_when_players_near():
    a = stream_tile_bubble(1000, 2000, tile_size=512, radius=2)
    b = stream_tile_bubble(1100, 2050, tile_size=512, radius=2)
    assert len(a & b) > 0
    far = stream_tile_bubble(5_000_000, 8_000_000, tile_size=512, radius=2)
    assert len(a & far) == 0


def test_full_window_never_slides():
    pack = EarthGrid(width=512, height=512, tile_size=512)
    win = LocalWindow(
        grid=pack,
        size=512,
        multiplayer_origin_mode="SoloSlide",
        fold_host_into_pack=True,
        enable_longitude_wrap=False,
    )
    win.set_origin(0, 0)
    # edge position would normally slide; full window blocks it
    slid, *_ = win.tick_player_local(10, 10)
    assert slid is False


def test_multi_player_union_keeps_far_bubbles():
    """Far-apart players: hot set is union; single-center would drop one bubble."""
    foci = [(1000, 2000), (5_000_000, 8_000_000)]
    hot = multi_player_hot_tiles(foci, tile_size=512, radius=2)
    a = stream_tile_bubble(1000, 2000, tile_size=512, radius=2)
    b = stream_tile_bubble(5_000_000, 8_000_000, tile_size=512, radius=2)
    assert a.issubset(hot)
    assert b.issubset(hot)
    assert len(hot) == len(a) + len(b)


def test_multi_center_evict_preserves_both_groups():
    foci = [(1000, 2000), (5_000_000, 8_000_000)]
    hot = multi_player_hot_tiles(foci, tile_size=512, radius=2)
    # After "update" at same foci with unload=5, nothing in hot should go
    gone = tiles_to_evict(hot, foci, tile_size=512, unload_radius=5)
    assert gone == set()
    # Stray tile far from both foci is evicted
    stray = {(99999, 99999)}
    gone2 = tiles_to_evict(hot | stray, foci, tile_size=512, unload_radius=5)
    assert (99999, 99999) in gone2
    assert not (gone2 & hot)


def test_mp_config_shared_fixed_keys():
    """Config/realearth.mp.json ships SharedFixed for dedicated MP."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    cfg = json.loads((root / "Config" / "realearth.mp.json").read_text(encoding="utf-8"))
    assert cfg["MapMode"] == "Streamed"
    assert cfg["MultiplayerOriginMode"] == "SharedFixed"
    assert cfg["EnableEngineHeightMod"] is True
    assert int(cfg["StreamRadiusTiles"]) >= 2
    assert int(cfg["UnloadRadiusTiles"]) >= int(cfg["StreamRadiusTiles"])


def test_ensure_hot_mirror_does_not_evict_other_foci():
    """Inject-style ensure around one point must not remove the other group's keep set.

    Mirrors C#: EnsureHotAround loads only; eviction is only on UpdateFromAbsolute foci.
    """
    foci = [(1000, 2000), (5_000_000, 8_000_000)]
    hot = multi_player_hot_tiles(foci, tile_size=512, radius=2)
    # "EnsureHotAround" a third inject point: union load, no focus register
    inject_bubble = stream_tile_bubble(3000, 4000, tile_size=512, radius=1)
    hot2 = hot | inject_bubble
    # Eviction still based only on player foci (not inject point)
    gone = tiles_to_evict(hot2, foci, tile_size=512, unload_radius=5)
    # Inject-only tiles far from both foci may go — player tiles must stay
    assert not (gone & hot)

