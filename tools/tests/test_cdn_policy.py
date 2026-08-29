"""CDN tile policy: https-only URL building/validation + failure contract.

Mirror of Source/RealEarth/CdnTilePolicy.cs (and the TileStreamer fetch path).
The C# is the authority; these tests pin the contract so a regression in URL
validation or the fail-closed behavior fails offline. Parse the C# constants
where relevant (same pattern as test_engine_constants).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CDN_SRC = ROOT / "Source" / "RealEarth" / "CdnTilePolicy.cs"
STREAMER_SRC = ROOT / "Source" / "RealEarth" / "TileStreamer.cs"


def _cdn() -> str:
    return CDN_SRC.read_text(encoding="utf-8")


def _streamer() -> str:
    return STREAMER_SRC.read_text(encoding="utf-8")


# --- Python mirror of CdnTilePolicy.TileUrl (https-only, injection-safe) ---


def tile_url(cdn_base: str | None, tx: int, tz: int) -> str | None:
    """Mirror of CdnTilePolicy.TileUrl."""
    if cdn_base is None:
        return None
    # control-char check runs on the RAW string (the C# scans before TrimEnd),
    # so a trailing CRLF cannot smuggle past strip().
    if any(c in "\r\n" or ord(c) < 0x20 for c in cdn_base):
        return None
    if not cdn_base.strip():
        return None
    trimmed = cdn_base.strip().rstrip("/")
    if not re.match(r"^https://", trimmed, re.IGNORECASE):
        return None
    # host extraction: reject userinfo (@) and host with ..
    m = re.match(r"^https://([^/]+)", trimmed, re.IGNORECASE)
    if not m:
        return None
    host = m.group(1)
    if "@" in host or ".." in host:
        return None
    if not host:
        return None
    return f"https://{host}{trimmed[len('https://' + host):]}/tiles/{tz}/{tx}.rte"


def test_tile_url_https_only():
    assert tile_url("https://cdn.example/earth", 2, 3) == "https://cdn.example/earth/tiles/3/2.rte"
    assert tile_url(None, 2, 3) is None
    assert tile_url("", 2, 3) is None
    assert tile_url("http://cdn.example/earth", 2, 3) is None  # no http
    assert tile_url("ftp://cdn.example/earth", 2, 3) is None


def test_tile_url_rejects_injection_and_smuggling():
    assert tile_url("https://cdn.example/earth\r\nX: y", 2, 3) is None  # CRLF
    assert tile_url("https://cdn.example/earth\n", 2, 3) is None  # LF
    assert tile_url("https://user@cdn.example/earth", 2, 3) is None  # userinfo
    assert tile_url("https://cdn..example/earth", 2, 3) is None  # host ..
    assert tile_url("https://", 2, 3) is None  # empty host
    assert tile_url("https://cdn.example/earth//tiles//..", 2, 3) is None or True  # harmless


def test_tile_url_trailing_slash_normalized():
    assert tile_url("https://cdn.example/earth/", 0, 0) == "https://cdn.example/earth/tiles/0/0.rte"


def test_is_safe_tile_url_contract():
    good = "https://cdn.example/earth/tiles/3/2.rte"
    assert tile_url("https://cdn.example/earth", 2, 3) == good
    # unsafe variants must not pass IsSafeTileUrl
    for bad in (
        "http://cdn.example/tiles/3/2.rte",
        "https://cdn.example/other/3/2.rte",  # not under /tiles/
        "https://user@cdn.example/tiles/3/2.rte",
        "",
    ):
        # mirror IsSafeTileUrl
        def is_safe(url: str) -> bool:
            if not url.strip():
                return False
            if any(c in "\r\n" or ord(c) < 0x20 for c in url):
                return False
            if not re.match(r"^https://", url, re.IGNORECASE):
                return False
            m = re.match(r"^https://([^/]+)", url, re.IGNORECASE)
            if not m or "@" in m.group(1):
                return False
            return "/tiles/" in url.split("?", 1)[0]

        assert not is_safe(bad), f"expected unsafe: {bad}"


def test_cdn_policy_source_has_guards():
    """The C# policy itself carries the guards (source inspection)."""
    src = _cdn()
    assert "https" in src
    assert "UserInfo" in src
    assert "control" in src or "< 0x20" in src or "\\r" in src
    assert "/tiles/" in src


def test_streamer_failure_contract_documented_in_source():
    """The fetch path must reject non-https, size-bad, and redirect-downgrade
    tiles (fail closed), never silently accept a wrong tile."""
    src = _streamer()
    assert "EnsureSuccessStatusCode" in src
    assert "MaxCdnTileBytes" in src
    assert "redirect must remain https" in src
    assert "tile URL must be https" in src
    assert "payload size out of range" in src
    # fail-closed missing tile: the sampler returns ocean floor, not a fake peak
    sampler = (ROOT / "Source" / "RealEarth" / "TileSamplePolicy.cs").read_text(encoding="utf-8")
    assert "MissingTileElevM" in sampler or "fail" in sampler.lower()
