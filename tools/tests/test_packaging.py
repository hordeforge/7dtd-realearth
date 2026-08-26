"""Packaging contract for the shipped mod folder and Python wheel.

The mod folder produced by scripts/package_mod.sh is the artifact users
download and redistribute, so its manifest version, license text, and doc set
are pinned here without building a package.
"""

from __future__ import annotations

import re
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


def test_package_mod_does_not_ship_repo_hub_docs():
    """docs/INDEX.md is maintainer navigation: its links target sibling repos,
    workspace files, and repo-root docs that do not exist inside the shipped
    folder."""
    src = _read("scripts/package_mod.sh")
    assert 'cp "$ROOT/docs/INDEX.md" "$OUT/Docs/"' not in src
