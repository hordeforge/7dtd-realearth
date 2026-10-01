"""Structural assertions on cache invalidation at the write paths.

Covers the process-static, world-scoped memos whose source of truth is the
session origin or the world roster:
- WorldSession.SetOrigin drops the memoized place locals (city pins, POI stamps)
- WorldSession player-count TTL cache is dropped when the world changes
- TileStreamer negative cache stays bounded (guard for an existing invariant)
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Source" / "RealEarth"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _body_between(src: str, start: str, end: str) -> str:
    i = src.index(start)
    j = src.index(end, i)
    assert i < j, f"end marker not after start marker: {start}"
    return src[i:j]


def test_origin_write_drops_place_local_memo():
    """Every host-local coord derived from lon/lat is memoized on Place.LocalValid,
    and every origin write (slide, snapshot restore, `resession load`) moves it.
    The invalidation belongs at the single write, not in each caller."""
    src = _read("WorldSession.cs")
    body = _body_between(
        src,
        "public void SetOrigin(int earthX, int earthZ)",
        "Restore a saved snapshot",
    )
    guard = body.index("if (ox == prevX && oz == prevZ)")
    write = body.index("WriteOriginLocked(ox, oz)")
    assert guard < write, "unchanged origin must not run the invalidation"
    assert body.index("CityMapLabels.InvalidateOriginDerivedCache()") > write
    assert body.index("RuntimePoiInject.InvalidateOriginDerivedCache()") > write


def test_city_label_origin_invalidation_drops_pins_and_memo():
    """A placed nav pin is anchored at a host-local cell, so an origin move
    leaves every pin behind: unregister them and drop the memo together."""
    src = _read("CityMapLabels.cs")
    body = _body_between(
        src,
        "public static void InvalidateOriginDerivedCache()",
        "Legacy entry",
    )
    assert "lock (_cityGate)" in body
    assert "UnregisterAllNavOnly()" in body
    assert "InvalidateLocalCache()" in body
    assert "_tickThrottle = 0" in body


def test_poi_origin_invalidation_keeps_placed_set():
    """POI stamps survive an origin move (chunk blocks are not remapped), so the
    origin invalidation must drop only the place-local memo, never _placed."""
    src = _read("RuntimePoiInject.cs")
    body = _body_between(
        src,
        "public static void InvalidateOriginDerivedCache()",
        "public static void InvalidatePlacesCatalog()",
    )
    assert "lock (_stampGate)" in body
    assert "InvalidateLocalCache()" in body
    code = re.sub(r"//[^\n]*", "", body)
    assert "_placed" not in code, "origin move must not re-arm already placed POIs"
    assert "_chunkCounts" not in code, "chunk budget is the slide path's to reset"


def test_player_count_cache_is_dropped_when_the_world_changes():
    """EstimatePlayerCount is process-static with a TTL, but the count belongs to
    the current world. Reading a new world through the previous world's roster
    makes the MP/solo slide policy decide on a player count that is not there."""
    src = _read("WorldSession.cs")
    reset = _body_between(
        src,
        "public static void ResetPlayerCountCache()",
        "static int EstimatePlayerCountUncached",
    )
    assert "_playerCountCacheValid = false" in reset
    ready = _body_between(
        _read("RuntimeHooks.cs"),
        "public static void WorldReadyPostfix",
        "SessionStateStore.TrySave(session, cfg)",
    )
    assert "WorldSession.ResetPlayerCountCache()" in ready


def test_tile_negative_cache_stays_bounded():
    """Miss deadlines are per (tx, tz); a pack with missing tiles would otherwise
    leave one entry per failed tile for the whole server uptime."""
    src = _read("TileStreamer.cs")
    mark = _body_between(
        src,
        "void MarkMiss(long key)",
        "Caller holds _lock",
    )
    assert "MissCachePruneThreshold" in mark
    assert "PruneExpiredMissesLocked()" in mark
    assert "MissCacheMs" in src


def test_focus_map_has_a_stale_sweep():
    """Unload postfixes are best-effort reflection; a focus whose player left must
    not pin its tiles hot for the whole process lifetime."""
    src = _read("TileStreamer.cs")
    assert re.search(r"FocusStaleMs\s*=\s*[\d_]+", src)
    sweep = _body_between(src, "bool SweepStaleFociLocked(int now)", "int FoldPackZ")
    assert "FocusStaleMs" in sweep


def test_last_focus_leaving_drops_the_miss_cache_too():
    """The hot set and the miss deadlines share one session.

    Clearing only the hot set leaves up to MissCacheMs of deadlines from a
    player who has left, so the next session reads tiles that may have been
    written to the durable store since as fail-closed ocean.
    """
    src = _read("TileStreamer.cs")
    body = _body_between(src, "public void RemoveFocus(int focusId)", "bool SweepStaleFociLocked")
    clear = body.index("if (_foci.Count == 0)")
    done = body.index("return;", clear)
    branch = body[clear:done]
    assert "_hot.Clear()" in branch
    assert "_missUntilTick.Clear()" in branch
