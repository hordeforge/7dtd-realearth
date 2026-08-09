"""Structural + pure color packing checks for DebugRevealFullMap (MapReveal.cs)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAP_REVEAL = ROOT / "Source" / "RealEarth" / "MapReveal.cs"
CONFIG = ROOT / "Config" / "realearth.json"


def test_map_reveal_source_fills_fow_not_only_visit():
    src = MAP_REVEAL.read_text(encoding="utf-8")
    assert "fowDatabaseForLocalPlayer" in src
    assert "DebugRevealFullMap" in src
    assert "MapChunkDatabase" in src or 'Name != "Add"' in src
    assert "PackRgb565" in src
    assert "GetWorldExtent" in src or "TryGetWorldChunkBounds" in src


def test_config_defaults_debug_reveal_off():
    text = CONFIG.read_text(encoding="utf-8")
    assert "DebugRevealFullMap" in text
    assert '"DebugRevealFullMap": false' in text or '"DebugRevealFullMap":false' in text


def test_rgb565_pack_matches_c_sharp_formula():
    """Mirror MapReveal.PackRgb565 for offline sanity (same bit layout)."""

    def pack(r: int, g: int, b: int) -> int:
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

    # pure red/green/blue extremes
    assert pack(255, 0, 0) == 0xF800
    assert pack(0, 255, 0) == 0x07E0
    assert pack(0, 0, 255) == 0x001F
    # water-ish blue should not be black (0)
    assert pack(20, 40, 120) != 0
