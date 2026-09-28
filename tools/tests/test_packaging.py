"""Packaging contract for the shipped mod folder and Python wheel.

The mod folder produced by scripts/package_mod.sh is the artifact users
download and redistribute, so its manifest version, license text, doc set, and
"incomplete folder is a failure, not a warning" rule are pinned here. The
guards run the real script against a throwaway copy of the repo layout.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import realearth

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _shipped_version() -> str:
    m = re.search(r'<Version value="([^"]+)"', _read("ModInfo.xml"))
    assert m, "ModInfo.xml has no <Version value=...>"
    return m.group(1)


def test_wheel_version_matches_shipped_mod_version():
    """realearth.__version__ feeds the wheel/sdist version and claims to match
    ModInfo.xml; drift would ship a pipeline labeled with a foreign mod
    version."""
    assert realearth.__version__ == _shipped_version()


def test_changelog_has_released_entry_for_shipped_version():
    """The shipped version must be an actual CHANGELOG release heading."""
    v = _shipped_version()
    assert re.search(
        rf"^## \[{re.escape(v)}\] - \d{{4}}-\d{{2}}-\d{{2}}\s*$",
        _read("CHANGELOG.md"),
        re.M,
    ), f"CHANGELOG.md has no released entry for {v}"


def test_package_mod_ships_license_text():
    """The mod folder is redistributed standalone (mod sites, server packs);
    MIT requires the license text to travel with it."""
    src = _read("scripts/package_mod.sh")
    assert 'cp "$ROOT/LICENSE"' in src


def test_package_mod_ships_optional_config_modlets():
    """spawning/buffs/nav_objects copy when present (spawn pressure, altitude, cities)."""
    src = _read("scripts/package_mod.sh")
    assert "Config/spawning.xml" in src
    assert "Config/gamestages.xml" in src
    assert "Config/buffs.xml" in src
    assert "Config/nav_objects.xml" in src
    assert "Config/XUi_InGame" in src


def test_package_mod_does_not_ship_repo_hub_docs():
    """docs/INDEX.md is maintainer navigation: its links target sibling repos,
    workspace files, and repo-root docs that do not exist inside the shipped
    folder."""
    src = _read("scripts/package_mod.sh")
    assert 'cp "$ROOT/docs/INDEX.md" "$OUT/Docs/"' not in src


def _fake_root(tmp_path: Path) -> Path:
    """A repo root the packaging script can read, without data/samples."""
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "package_mod.sh", root / "scripts" / "package_mod.sh")
    for name in ("tools", "Config", "docs"):
        (root / name).symlink_to(ROOT / name, target_is_directory=True)
    for name in ("ModInfo.xml", "LICENSE", "ATTRIBUTION.md", "CHANGELOG.md"):
        (root / name).symlink_to(ROOT / name)
    return root


def _run_package_mod(root: Path, out: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    env_all = dict(os.environ)
    env_all.pop("SEVENDTD_GAME_DIR", None)
    env_all.pop("GAME_DIR", None)
    env_all.pop("DOTNET_ROOT", None)
    env_all.update(env)
    return subprocess.run(
        ["bash", str(root / "scripts" / "package_mod.sh"), str(out)],
        capture_output=True,
        text=True,
        check=False,
        env=env_all,
    )


def test_package_mod_fails_when_streamed_pack_is_missing(tmp_path):
    """Streamed samples Data/tiles at runtime and a packaged config carries no
    CDN base URL, so a folder without a pack renders nothing: fail the build."""
    root = _fake_root(tmp_path)
    result = _run_package_mod(root, tmp_path / "out", {"MAP_MODE": "Streamed"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "make demo" in result.stderr
    assert not (tmp_path / "out" / "Data" / "tiles").exists()


def test_package_mod_fails_without_the_mod_dll(tmp_path):
    """7DTD loads the mod through RealEarth.dll; a folder without it is empty
    at runtime. Baked mode passes the pack guard, so this isolates the DLL one."""
    root = _fake_root(tmp_path)
    result = _run_package_mod(root, tmp_path / "out", {"MAP_MODE": "Baked"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "RealEarth.dll" in result.stderr


def test_install_fails_when_streamed_pack_is_missing(tmp_path):
    """Same rule on the install path, checked before install_mod removes the
    previous install, so `make install` cannot leave a mod with no data."""
    root = _fake_root(tmp_path)
    shutil.copy2(ROOT / "scripts" / "install_proton.sh", root / "scripts" / "install_proton.sh")
    game = tmp_path / "game"
    (game / "7DaysToDie_Data" / "Managed").mkdir(parents=True)
    (game / "Mods" / "0_TFP_Harmony").mkdir(parents=True)
    result = _run_install(root, {"SEVENDTD_GAME_DIR": str(game)})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "make demo" in result.stderr
    assert not (game / "Mods" / "RealEarth").exists()


def _run_install(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    env_all = dict(os.environ)
    env_all.pop("SEVENDTD_GAME_DIR", None)
    env_all.pop("GAME_DIR", None)
    env_all.pop("DOTNET_ROOT", None)
    env_all.update(env)
    return subprocess.run(
        ["bash", str(root / "scripts" / "install_proton.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env_all,
    )
