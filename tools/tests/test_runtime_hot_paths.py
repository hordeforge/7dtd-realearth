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
    assert needs < claims, (
        "HasLandClaims must be gated behind the cheap NeedsRecentering band check"
    )


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
    assert "Environment.TickCount" in body
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
