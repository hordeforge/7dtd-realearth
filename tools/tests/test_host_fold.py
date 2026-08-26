"""Host-world fold into pack grid (shipped local_window fold rules).

Drives realearth.local_window.fold_x / fold_z, the same functions the
LocalWindow fold path and test_multiplayer exercise, so a change to production
folding fails here instead of silently passing against a test-local copy.
"""

from realearth.local_window import fold_x, fold_z


def test_fold_large_host_chunk_into_pack():
    """chunk 2048 -> block 32768 must land inside 512 pack (not ClampZ-only)."""
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


def test_fold_degenerate_extent_stays_in_range():
    assert fold_x(-7, 0) == 0
    assert fold_z(-7, 1) == 0


def test_fold_is_modulo_consistent_for_signed_hosts():
    """Every k*pack offset of a packed cell folds back to that cell."""
    pack = 512
    peak = 256
    for k in range(-10, 10):
        host = peak + k * pack
        assert fold_x(host, pack) == peak
        assert fold_z(host, pack) == peak
