"""The install scripts must publish a mod over the live one, never over a hole.

scripts/atomic_dir_swap.sh is the mechanism: fill a sibling staging dir, then
swap it onto the destination with renames. These tests run it for real, because
the failure they guard against (a Mods/RealEarth that is empty or half-copied
when an install dies) is invisible in a source grep.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "atomic_dir_swap.sh"


def _bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'set -euo pipefail\nsource "{HELPER}"\n{script}'],
        capture_output=True,
        text=True,
        check=True,
    )


def _leftovers(parent: Path, name: str) -> list[Path]:
    return sorted(p.name for p in parent.iterdir() if name in p.name)


def test_publish_replaces_live_content_and_leaves_no_debris(tmp_path: Path) -> None:
    dest = tmp_path / "Mods" / "RealEarth"
    dest.mkdir(parents=True)
    (dest / "old.dll").write_text("stale", encoding="utf-8")

    _bash(f"""
        atomic_swap_begin "{dest}"
        echo fresh > "$RE_ATOMIC_STAGING/RealEarth.dll"
        atomic_swap_publish "{dest}"
        """)

    assert not (dest / "old.dll").exists()
    assert (dest / "RealEarth.dll").read_text(encoding="utf-8") == "fresh\n"
    assert _leftovers(tmp_path / "Mods", "RealEarth") == ["RealEarth"]


def test_failed_fill_leaves_the_previous_install_intact(tmp_path: Path) -> None:
    dest = tmp_path / "Mods" / "RealEarth"
    dest.mkdir(parents=True)
    (dest / "RealEarth.dll").write_text("working", encoding="utf-8")

    # What an interrupted install does: start staging, write part of the tree,
    # then die. atomic_swap_cleanup is the EXIT trap the install scripts set.
    _bash(f"""
        atomic_swap_begin "{dest}"
        echo partial > "$RE_ATOMIC_STAGING/RealEarth.dll"
        atomic_swap_cleanup
        """)

    assert (dest / "RealEarth.dll").read_text(encoding="utf-8") == "working"
    assert _leftovers(tmp_path / "Mods", "RealEarth") == ["RealEarth"]


def test_publish_without_begin_is_refused(tmp_path: Path) -> None:
    dest = tmp_path / "Mods" / "RealEarth"
    dest.mkdir(parents=True)
    (dest / "RealEarth.dll").write_text("working", encoding="utf-8")

    result = subprocess.run(
        ["bash", "-c", f'source "{HELPER}"\natomic_swap_publish "{dest}"'],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "atomic_swap_begin" in result.stderr
    assert (dest / "RealEarth.dll").read_text(encoding="utf-8") == "working"


def test_install_script_publishes_instead_of_deleting_the_live_folder() -> None:
    """install_proton.sh must not rm -rf the mod or world it is replacing."""
    src = (ROOT / "scripts" / "install_proton.sh").read_text(encoding="utf-8")
    assert 'source "$ROOT/scripts/atomic_dir_swap.sh"' in src
    assert 'rm -rf "$dest"' not in src
    assert "trap atomic_swap_cleanup EXIT" in src
    # The mod and the generated world both go through the swap.
    assert src.count("atomic_swap_publish") == 2
