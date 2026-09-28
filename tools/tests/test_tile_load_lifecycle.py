"""Structural assertions on the async tile-load claim and its release.

A queued load owns two things: the in-flight claim on its tile key and one of
the bounded concurrency slots. Both live for exactly the duration of the load,
so every exit path has to hand them back. The claim also has no expiry, so a
load that never runs pins its tile for the whole server uptime; the slot set
grows with player speed, so an unbounded one turns one stalled CDN into
unbounded sockets and read buffers.
"""

from __future__ import annotations

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


def _queue_load() -> str:
    return _body_between(
        _read("TileStreamer.cs"),
        "void QueueLoad(int tx, int tz, string path, long key, bool fromCdn)",
        "void TryLoadLocalSync",
    )


def _load_body() -> str:
    return _body_between(
        _read("TileStreamer.cs"),
        "async Task LoadTileFireAndForget",
        "void EvictOutsideAllFoci",
    )


def test_async_loads_are_bounded():
    """The pending-load set is capped, and the cap is a named constant rather
    than a literal, so the ceiling is one auditable number."""
    src = _read("TileStreamer.cs")
    assert "internal const int MaxConcurrentAsyncLoads = " in src
    queue = _queue_load()
    assert "_asyncLoadSlots.Count >= MaxConcurrentAsyncLoads" in queue
    assert "_asyncLoadSlots.Add(key)" in queue


def test_over_cap_tiles_are_retried_not_cached_as_misses():
    """A refused tile must stay uncached AND un-missed: a miss deadline written
    here would expire MissCacheMs later and pin the tile on fail-closed ocean
    even though no load ever ran."""
    queue = _queue_load()
    refuse = queue.index("MaxConcurrentAsyncLoads")
    claim = queue.index("_loadInFlight.Add(key)")
    assert refuse < claim, "the cap must be checked before the claim is taken"
    assert "MarkMiss" not in queue, "a refused load must not write a miss deadline"


def test_dispatch_failure_returns_the_claim():
    """DispatchAsyncLoad runs outside the load's try/finally, so a dispatcher
    that throws synchronously skips the release and leaves the claim set
    growing for the process lifetime."""
    queue = _queue_load()
    assert queue.index("try") < queue.index("DispatchAsyncLoad") < queue.index("catch")
    catch = queue[queue.index("catch") :]
    assert "_loadInFlight.Remove(key)" in catch
    assert "_asyncLoadSlots.Remove(key)" in catch


def test_nothing_evaluates_before_the_guarded_region():
    """The url resolve sat above the try, so a throw there skipped the finally
    that owns the claim. Only declarations may precede it now."""
    body = _load_body()
    guarded = body.index("\n            try\n")
    assert body.index("CdnTilePolicy.TileUrl") > guarded
    assert (
        body.index("Stopwatch.StartNew()") < guarded
    ), "the stopwatch is allocation-free and cannot throw; only the url resolve moved"


def test_load_returns_its_slot_on_every_exit_path():
    """The finally is the single release for both the claim and the slot, and
    the slot is dropped by key so a load that lost its claim to a timed-out
    sync load still gives its capacity back."""
    body = _load_body()
    tail = body[body.rindex("finally") :]
    assert "_asyncLoadSlots.Remove(key)" in tail
    assert "_loadInFlight.Remove(key)" in tail
    assert (
        "MarkMiss" in body and "return;" in body
    ), "early returns must be inside the guarded region"


def test_streamer_releases_its_http_client():
    """The streamer owns an HttpClient, which owns a connection pool. Assigning
    a new streamer over an old one used to strand the previous pool and its
    decoded hot set for the process lifetime."""
    src = _read("TileStreamer.cs")
    assert "public sealed class TileStreamer : IDisposable" in src
    dispose = _body_between(src, "public void Dispose()", "\n    }\n}")
    assert "_http.Dispose()" in dispose
    assert "GC.SuppressFinalize(this)" in dispose

    modapi = _read("ModApi.cs")
    assign = modapi.index("Streamer = new TileStreamer")
    assert 0 < modapi.index("Streamer?.Dispose();") < assign
