"""Config contract between shipped scripts, mod config, and C# loader.

Pins the product defaults so install/package scripts cannot drift back to
debug-on or StockSafe-on fallbacks (HEIGHT_LIMITS.md: StockSafe is not product).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Source" / "RealEarth"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _script_body(rel: str) -> str:
    """All Python heredoc bodies inside a shell script, concatenated."""
    src = _read(rel)
    bodies = re.findall(r"<<'PY'[^\n]*\n(?P<body>.*?)\nPY\n", src, re.S)
    assert bodies, f"python heredoc not found in {rel}"
    return "\n".join(bodies)


def test_install_script_defaults_stocksafe_off():
    """install_proton.sh must fall back to EngineHeightStockSafe=false (product rule)."""
    body = _script_body("scripts/install_proton.sh")
    m = re.search(
        r'cfg\["EngineHeightStockSafe"\]\s*=\s*bool\(cfg\.get\('
        r'"EngineHeightStockSafe",\s*(?P<dflt>\w+)\)\)',
        body,
    )
    assert m, "EngineHeightStockSafe fallback missing from install_proton.sh"
    assert m.group("dflt") == "False", (
        "install_proton.sh must default EngineHeightStockSafe to False "
        "(real meters are the product path; True silently compresses heights)"
    )


def test_packaged_config_ships_debug_fow_off():
    """package_mod.sh must ship with debug FOW keys off."""
    body = _script_body("scripts/package_mod.sh")
    assert 'cfg.setdefault("DebugRevealFullMap", False)' in body
    assert 'cfg.setdefault("DebugMapRevealRadiusChunks", 0)' in body


def test_height_pack_install_ships_stocksafe_off():
    """install_height_pack.sh must not opt installs into StockSafe compress
    (HEIGHT_LIMITS.md: operator opt-in only; silent 0-250 squash otherwise)."""
    src = _read("scripts/install_height_pack.sh")
    assert '"EngineHeightStockSafe=false"' in src, (
        "install_height_pack.sh must write EngineHeightStockSafe=false "
        "(unexpanded engines must hit the loud ExpandProductGuard, not compress)"
    )
    for path in sorted((ROOT / "scripts").glob("*.sh")):
        assert "EngineHeightStockSafe=true" not in path.read_text(encoding="utf-8"), (
            f"{path.name} forces EngineHeightStockSafe=true (not product)"
        )


def test_install_script_validates_map_mode():
    """MAP_MODE other than Streamed|Baked must fail the install, not become Baked."""
    src = _read("scripts/install_proton.sh")
    assert re.search(r"Streamed\|Baked\)", src), "MAP_MODE case validation missing"


def test_shipped_configs_match_product_defaults():
    """Shipped realearth.json profiles keep real-height on and debug FOW off
    (advanced_height.json is the documented dev template and may differ)."""
    for name in ("realearth.json", "realearth.mp.json"):
        cfg = json.loads(_read(f"Config/{name}"))
        assert cfg["MapMode"] in ("Streamed", "Baked"), name
        assert cfg["MultiplayerOriginMode"] in ("SoloSlide", "SharedFixed", "SharedSlide"), name
        assert cfg["EnableEngineHeightMod"] is True, name
        assert cfg["EngineHeightStockSafe"] is False, name
        assert cfg["DebugRevealFullMap"] is False, name
        assert cfg["DebugMapRevealRadiusChunks"] == 0, name
        assert cfg["UnloadRadiusTiles"] > cfg["StreamRadiusTiles"], name


def test_config_validate_exists_and_runs_at_init():
    """RealEarthConfig.Validate() must clamp/warn and be called right after Load."""
    src = _read("Source/RealEarth/RealEarthConfig.cs")
    assert "public IReadOnlyList<string> Validate()" in src
    # Enum-like strings must list valid values in the warning text.
    for token in ("Streamed", "Baked", "SoloSlide", "SharedFixed", "SharedSlide"):
        assert token in src
    # Unload radius must be forced above stream radius (thrash guard).
    assert "UnloadRadiusTiles = StreamRadiusTiles + 1" in src
    api = _read("Source/RealEarth/ModApi.cs")
    m = re.search(
        r'RealEarthConfig\.Load\(Path\.Combine\(ModPath, "Config", "realearth\.json"\)\);\n'
        r"\s*foreach \(var warning in Config\.Validate\(\)\)",
        api,
    )
    assert m, "InitMod must run Config.Validate() immediately after Load"
