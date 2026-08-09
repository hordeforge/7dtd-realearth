"""Host-world fold into pack grid (mirrors WorldSession/TileStreamer fold rules)."""


def fold_x(x: int, width: int) -> int:
    w = max(1, width)
    r = x % w
    return r if r >= 0 else r + w


def fold_z(z: int, height: int) -> int:
    h = max(1, height)
    r = z % h
    return r if r >= 0 else r + h


def test_fold_large_host_chunk_into_pack():
    """chunk 2048 → block 32768 must land inside 512 pack (not ClampZ-only)."""
    pack = 512
    block = 2048 * 16  # 32768
    assert fold_x(block, pack) == 0
    assert fold_z(block, pack) == 0
    # center of pack via host offset
    assert fold_x(256 + pack * 3, pack) == 256
    assert fold_z(256 + pack * 7, pack) == 256


def test_fold_negative_coords():
    assert fold_x(-1, 512) == 511
    assert fold_z(-16, 512) == 496


def test_peak_cell_reachable_from_many_host_tiles():
    """Any host tile that maps to pack center samples peak column."""
    pack = 512
    peak = 256
    for k in range(0, 20):
        host = peak + k * pack
        assert fold_x(host, pack) == peak
        assert fold_z(host, pack) == peak
