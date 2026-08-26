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


def test_install_script_defaults_stocksafe_off():
    """install_proton.sh must fall back to EngineHeightStockSafe=false (product rule)."""
    src = _read("scripts/install_proton.sh")
    assert '"EngineHeightStockSafe?=false"' in src, (
        "install_proton.sh must default EngineHeightStockSafe to false "
        "(real meters are the product path; true silently compresses heights)"
    )


def test_packaged_config_ships_debug_fow_off():
    """package_mod.sh must ship with debug FOW keys off."""
    src = _read("scripts/package_mod.sh")
    assert '"DebugRevealFullMap?=false"' in src
    assert '"DebugMapRevealRadiusChunks?=0"' in src


def test_no_shell_script_embeds_python():
    """Config writing lives in realearth.mod_config / realearth.server_config.

    A heredoc splices shell values into a Python source body, so a world name or
    path holding a quote becomes executable code; it also puts the logic beyond
    the reach of these tests.
    """
    for path in sorted((ROOT / "scripts").glob("*.sh")):
        src = path.read_text(encoding="utf-8")
        assert not re.search(
            r"python3?\s+(-c|-\s*<<)", src
        ), f"{path.name} embeds python; call a realearth module instead"


def test_height_pack_install_ships_stocksafe_off():
    """install_height_pack.sh must not opt installs into StockSafe compress
    (HEIGHT_LIMITS.md: operator opt-in only; silent 0-250 squash otherwise)."""
    src = _read("scripts/install_height_pack.sh")
    assert '"EngineHeightStockSafe=false"' in src, (
        "install_height_pack.sh must write EngineHeightStockSafe=false "
        "(unexpanded engines must hit the loud ExpandProductGuard, not compress)"
    )
    for path in sorted((ROOT / "scripts").glob("*.sh")):
        assert "EngineHeightStockSafe=true" not in path.read_text(
            encoding="utf-8"
        ), f"{path.name} forces EngineHeightStockSafe=true (not product)"


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
        assert cfg["MultiplayerOriginMode"] in (
            "SoloSlide",
            "SharedFixed",
            "SharedSlide",
        ), name
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


def _csharp_config_members() -> set[str]:
    """[DataMember] property names the C# loader actually deserializes."""
    src = _read("Source/RealEarth/RealEarthConfig.cs")
    return set(re.findall(r"\[DataMember\]\s*public\s+\S+\s+(\w+)\s*\{", src))


def test_shipped_config_keys_exist_in_csharp_loader():
    """Every shipped realearth.json key must map to a C# [DataMember].

    DataContractJsonSerializer silently drops keys it has no member for, so a
    typo'd or renamed key would do nothing at runtime with no error anywhere.
    Keys prefixed "_" are comment/metadata and exempt.
    """
    members = _csharp_config_members()
    assert "MapMode" in members  # sanity: the regex still matches the schema
    for name in (
        "realearth.json",
        "realearth.mp.json",
        "realearth.advanced_height.json",
    ):
        cfg = json.loads(_read(f"Config/{name}"))
        unknown = sorted(k for k in cfg if not k.startswith("_") and k not in members)
        assert not unknown, f"{name} has keys the mod loader ignores: {unknown}"


def test_script_window_default_matches_tools_constant():
    """Shell LOCAL_WINDOW_SIZE defaults must mirror realearth.DEFAULT_LOCAL_WINDOW_SIZE.

    The scripts cannot import the tools package (stdlib-only install path), so the
    1024 default is duplicated as a literal; this pins the copies so they cannot
    drift from the Python constant that names it.
    """
    from realearth import DEFAULT_LOCAL_WINDOW_SIZE

    for rel in ("scripts/install_proton.sh", "scripts/package_mod.sh"):
        src = _read(rel)
        match = re.search(r"^LOCAL_WINDOW_SIZE=(\d+)$", src, re.MULTILINE)
        assert match, f"{rel} lost its LOCAL_WINDOW_SIZE default"
        assert int(match.group(1)) == DEFAULT_LOCAL_WINDOW_SIZE, (
            f"{rel}: LOCAL_WINDOW_SIZE={match.group(1)} != "
            f"realearth.DEFAULT_LOCAL_WINDOW_SIZE={DEFAULT_LOCAL_WINDOW_SIZE}"
        )


def test_package_script_reads_documented_game_dir_knob():
    """package_mod.sh must read SEVENDTD_GAME_DIR then GAME_DIR.

    The Makefile exports GAME_DIR for this script and every other install/expand
    script reads SEVENDTD_GAME_DIR first; any other fallback spelling silently
    drops the DLL from the package.
    """
    src = _read("scripts/package_mod.sh")
    assert 'GAME_DIR="${SEVENDTD_GAME_DIR:-${GAME_DIR:-}}"' in src
