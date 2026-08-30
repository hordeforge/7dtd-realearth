"""Behavioral engine-patch lifecycle: expand, verify, stale marker, restore.

Uses the real EngineHeightPatcher.exe against a full copy of the game Managed
directory in a temp dir (no live install touched). Exercises the disk-patch
fallback path end to end: first expand, verify OK, Steam-update simulation
(stale marker + new stock bytes), reapply refreshes backup, restore returns
stock, fresh expand works again.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "tools" / "engine_patcher" / "bin" / "Release" / "EngineHeightPatcher.exe"
GAME_DIR = Path.home() / ".local/share/Steam/steamapps/common/7 Days To Die"
MANAGED = GAME_DIR / "7DaysToDie_Data" / "Managed"
STOCK_DLL = MANAGED / "Assembly-CSharp.dll"


def _patcher(dll: Path, *args: str) -> subprocess.CompletedProcess[str]:
    mono = shutil.which("mono")
    cmd = [mono, str(PATCHER)] if mono else [str(PATCHER)]
    return subprocess.run(
        cmd + ["--dll", str(dll), *args],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


@pytest.fixture(scope="module")
def managed_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Full copy of the game Managed dir so Mono.Cecil resolves every
    dependency of Assembly-CSharp when the patcher writes."""
    if not MANAGED.is_dir():
        pytest.skip("game Managed dir not installed")
    dst = tmp_path_factory.mktemp("managed")
    shutil.copytree(MANAGED, dst, dirs_exist_ok=True)
    return dst


def test_engine_expand_lifecycle(managed_copy: Path):
    dll = managed_copy / "Assembly-CSharp.dll"
    marker = dll.with_name(dll.name + ".re_height_expanded")
    backup = dll.with_name(dll.name + ".re_stock_bak")
    stock_bytes = dll.read_bytes()

    # 1. First expand: rewrites + marker + backup.
    r = _patcher(dll, "--ydim", "32768")
    assert r.returncode == 0, f"first expand failed: {r.stdout}\n{r.stderr}"
    assert marker.is_file(), "marker not created"
    assert backup.is_file(), "stock backup not created"
    assert backup.read_bytes() == stock_bytes, "backup must equal original stock"

    # 2. Verify OK against the marker sha256.
    r = _patcher(dll, "--verify")
    assert r.returncode == 0, f"verify failed: {r.stdout}"
    assert "Verify OK" in r.stdout

    # 3. Steam update: the DLL becomes fresh stock bytes; the marker is stale.
    dll.write_bytes(stock_bytes)
    r = _patcher(dll, "--verify")
    assert r.returncode != 0, "verify must fail after the DLL changed"

    # 4. Reapply (no --force): stale marker detected, backup refreshed to the
    #    new stock, then re-patched. Verify passes again.
    r = _patcher(dll, "--ydim", "32768")
    assert r.returncode == 0, f"reapply failed: {r.stdout}\n{r.stderr}"
    assert backup.read_bytes() == stock_bytes, "backup must refresh to new stock"
    r = _patcher(dll, "--verify")
    assert r.returncode == 0, "verify must pass after stale reapply"

    # 5. Restore (make engine-restore semantics): copy backup back, remove
    #    marker; verify then reports no marker.
    shutil.copy2(backup, dll)
    marker.unlink(missing_ok=True)
    r = _patcher(dll, "--verify")
    assert r.returncode != 0, "verify must fail on restored stock (no marker)"
    assert dll.read_bytes() == stock_bytes, "restored DLL must equal stock"

    # 6. Fresh expand on restored stock works again.
    r = _patcher(dll, "--ydim", "32768")
    assert r.returncode == 0, f"fresh expand after restore failed: {r.stdout}\n{r.stderr}"
    assert marker.is_file()
    r = _patcher(dll, "--verify")
    assert r.returncode == 0, "verify after re-expand failed"


def test_engine_expand_idempotent_already_patched(managed_copy: Path):
    """Running the patcher twice without --force on an already-expanded DLL is
    a no-op (marker matches), not a re-patch."""
    dll = managed_copy / "Assembly-CSharp.dll"
    marker = dll.with_name(dll.name + ".re_height_expanded")
    r = _patcher(dll, "--ydim", "32768")
    assert r.returncode == 0
    assert marker.is_file()
    r2 = _patcher(dll, "--ydim", "32768")
    assert r2.returncode == 0
    assert "Already patched" in r2.stdout
