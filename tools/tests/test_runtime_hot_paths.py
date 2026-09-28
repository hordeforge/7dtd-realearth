"""Structural assertions on shipped C# per-frame / chunk-gen hot paths.

Pins performance-relevant shape that unit mirrors cannot see:
- TickPlayerLocal must not run the land-claim reflection scan every tick
- EstimatePlayerCount must TTL-cache its four-deep reflection chain
- FillChunkColumns must sample each column once (not once per channel)
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Source" / "RealEarth"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _method_body(src: str, signature_regex: str, next_signature: str) -> str:
    m = re.search(signature_regex + r"(?P<body>.*?)" + re.escape(next_signature), src, re.S)
    assert m, f"method not found: {signature_regex}"
    return m.group("body")


def test_tick_slide_gates_claim_scan_behind_recentering():
    """OriginSlideRemap.HasLandClaims reflects over every player's claim sets;
    it must only run when NeedsRecentering says a slide is actually pending,
    not on every streamed player tick."""
    src = _read("WorldSession.cs")
    m = re.search(
        r"public bool TickPlayerLocal\((?P<params>[^)]*)\)(?P<body>.*?)"
        r"\n        public bool ShouldAllowOriginSlide\(\)",
        src,
        re.S,
    )
    assert m, "TickPlayerLocal not found"
    body = m.group("body")
    needs = body.index("NeedsRecentering")
    claims = body.index("HasLandClaims")
    assert (
        needs < claims
    ), "HasLandClaims must be gated behind the cheap NeedsRecentering band check"


def test_estimate_player_count_is_ttl_cached():
    """EstimatePlayerCount runs twice per non-primary entity tick via a
    GameManager→World→Players→Count reflection chain; results must be
    TTL-cached with an uncached core left intact."""
    src = _read("WorldSession.cs")
    assert "EstimatePlayerCountUncached" in src
    assert "PlayerCountCacheMs" in src
    m = re.search(
        r"public static int EstimatePlayerCount\(\)\s*\{(?P<body>.*?)\n        \}",
        src,
        re.S,
    )
    assert m, "EstimatePlayerCount not found"
    body = m.group("body")
    # TickNow() is the injectable Environment.TickCount source (virtual time in tests).
    assert "TickNow()" in body
    assert "EstimatePlayerCountUncached()" in body


def test_fill_chunk_columns_fuses_height_and_landcover_sample():
    """The streamed chunk fill used to call the streamer twice per column
    (height pass + landcover pass); both channels must come from one
    SampleColumnInt sample per column. The engine-height path keeps its
    dedicated store/policy sampling."""
    src = _read("ChunkTerrainSampler.cs")
    assert "SampleColumnInt" in src
    body = _method_body(
        src,
        r"public static void FillChunkColumns\(",
        "\n        /// <summary>",
    )
    assert "SampleColumnInt" in body, "fused fill must use SampleColumnInt"
    assert "SampleGameHeightIntExplicit" not in body.replace(
        "SampleColumnInt", ""
    ), "streamed branch must not rescan via the height-only path"
    # Engine-height branch keeps dedicated fills.
    assert "FillChunkHeightsInt" in body
    assert "FillChunkLandcover" in body
    # SampleColumnInt itself takes exactly one locked streamer sample.
    col = _method_body(
        src,
        r"static int SampleColumnInt\(",
        "\n        public static byte SampleLandcover(",
    )
    assert col.count("TrySamplePrefetch") == 1


def test_focus_map_has_ttl_sweep():
    """TileStreamer._foci removal relies on best-effort EntityPlayer unload
    postfixes; if none bind after a game update, every disconnect would pin its
    bubble tiles hot for the rest of server uptime. UpdateFromAbsolute must sweep
    foci silent past FocusStaleMs, and the same-tile fast path must refresh the
    heartbeat so idle-but-connected players are never swept."""
    src = _read("TileStreamer.cs")
    assert "FocusStaleMs" in src, "focus TTL constant missing"
    assert "SweepStaleFociLocked" in src, "stale-focus sweep missing"
    sig = (
        r"public void UpdateFromAbsolute"
        r"\(int earthX, int earthZ, int focusId, bool allowSyncLoad\)"
    )
    body = _method_body(
        src,
        sig,
        "\n        /// <summary>\n        /// Prefetch tiles",
    )
    assert "SweepStaleFociLocked(" in body, "per-tick focus update must run the sweep"
    # The same-tile early return must still write a fresh tick (heartbeat).
    heartbeat = (
        r"prev\.tx == tx && prev\.tz == tz.*?\n.*?"
        r"_foci\[focusId\] = \(earthX, earthZ, tx, tz, now\);"
    )
    assert re.search(
        heartbeat,
        body,
        re.S,
    ), "same-tile fast path must refresh the focus heartbeat"
    # Sweep uses wrap-safe TickCount delta like the miss cache.
    sweep = _method_body(
        src,
        r"bool SweepStaleFociLocked\(int now\)",
        "\n        /// <summary>",
    )
    assert "unchecked(now - kv.Value.tick)" in sweep


def test_cdn_tile_decode_precedes_durable_publish():
    """A CDN body that passes the RTE1 magic check but fails full decode must
    never be published into the local tile store: File.Exists would then route
    every later attempt to the poisoned disk copy instead of the CDN, pinning
    the tile on fail-closed ocean until manual cleanup. Both CDN paths must
    validate via RteTile.Decode before PublishTileBytes."""
    src = _read("TileStreamer.cs")
    sync = _method_body(
        src,
        r"void TryLoadCdnSync\(int tx, int tz, string path, long key, string url\)",
        "\n        /// <summary>\n        /// Durable publish",
    )
    assert sync.index("RteTile.Decode") < sync.index(
        "PublishTileBytes"
    ), "sync CDN path must decode-validate before publishing to disk"
    fire = _method_body(
        src,
        r"async Task LoadTileFireAndForget\(int tx, int tz, string path, long key, bool fromCdn\)",
        "\n        /// <summary>",
    )
    cdn_branch = fire[: fire.index("else")]
    assert cdn_branch.index("RteTile.Decode") < cdn_branch.index(
        "PublishTileBytes"
    ), "async CDN path must decode-validate before publishing to disk"


def test_per_tick_throttles_run_on_the_injected_clock():
    """Every time-gated per-tick decision must read the injectable TickNow seam,
    not Environment.TickCount. A wall-clock read makes the gate unsteppable: a
    harness driving virtual time can neither reproduce nor advance the throttle,
    so the same input run produces different buff/lon-lat/rescue state."""
    for rel, marker in (
        ("AltitudeClimateTick.cs", "MinIntervalMs"),
        ("LonLatHudTick.cs", "MinIntervalMs"),
        ("FallSpawnRetune.cs", "KillPlaneMinIntervalMs"),
    ):
        src = _read(rel)
        assert "internal static Func<int> TickNow" in src, f"{rel}: no TickNow seam"
        body = src[src.index(marker) :]
        assert "TickNow()" in body, f"{rel}: throttle does not read the injected clock"
        # One occurrence, the seam's own default; any other is a raw wall-clock read.
        code = re.sub(r"///.*|//.*", "", src)
        assert (
            code.count("Environment.TickCount") == 1
        ), f"{rel}: raw Environment.TickCount left in a time-driven decision"


def test_raw_wall_clock_reads_only_appear_as_seam_defaults():
    """Environment.TickCount may appear in runtime sources only as the default
    value of a TickNow seam. Anywhere else it is a wall-clock read the virtual
    clock cannot reach, so replaying the same seed diverges at that point."""
    for path in sorted(SRC.glob("*.cs")):
        code = re.sub(r"///.*|//.*", "", path.read_text(encoding="utf-8"))
        raw = code.count("Environment.TickCount")
        if not raw:
            continue
        seam = code.count("Func<int> TickNow { get; set; }")
        assert raw == seam, (
            f"{path.name}: {raw} raw Environment.TickCount read(s) but {seam} "
            "TickNow seam(s); every read must go through the seam"
        )


def test_async_tile_load_dispatch_and_claim_wait_are_injectable():
    """The two places the streamer hands control to the OS: the fire-and-forget
    load dispatch (completion order = hot-set contents) and the in-flight claim
    wait (real-time spin against a virtual clock). Both need a seam before any
    scheduler can step them."""
    src = _read("TileStreamer.cs")
    assert "internal static Action<Func<Task>> DispatchAsyncLoad" in src
    queue = _method_body(
        src,
        r"void QueueLoad\(int tx, int tz, string path, long key, bool fromCdn\)",
        "\n        void TryLoadLocalSync(",
    )
    assert "DispatchAsyncLoad(" in queue, "async load must go through the dispatch seam"
    assert "Task.Run" not in queue, "queueing must not start the load on an OS thread directly"
    assert "internal static Action<int> SleepMs" in src
    claim = _method_body(
        src,
        r"bool WaitForHotOrClaim\(long key, int maxWaitMs\)",
        "\n        void TryLoadCdnSync(",
    )
    assert "SleepMs(ClaimRetrySliceMs)" in claim
    assert "Thread.Sleep" not in claim, "claim wait must not burn real milliseconds"
