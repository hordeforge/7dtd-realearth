"""Audit height-query patch selection against live 3.0.1 Assembly-CSharp + shipped source.

Drives HeightQueryPatcher rules (mirrored for discovery) and asserts RuntimeHooks has no cap.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "Source" / "RealEarth" / "RuntimeHooks.cs"
PATCHER = ROOT / "Source" / "RealEarth" / "HeightQueryPatcher.cs"
INJECT = ROOT / "Source" / "RealEarth" / "ChunkTerrainInject.cs"
GAME_DLL = (
    Path.home()
    / ".local/share/Steam/steamapps/common/7 Days To Die"
    / "7DaysToDie_Data/Managed/Assembly-CSharp.dll"
)

# Mirror of HeightQueryPatcher.PreferredConcreteTypeNames + method names (must match C#)
PREFERRED = [
    "TerrainGeneratorWithBiomeResource",
    "TerrainFromRaw",
    "TerrainFromDTM",
    "TerrainFromImage",
]
HEIGHT_NAMES = {
    "GetTerrainHeightByteAt",
    "GetTerrainHeightAt",
    "GetTerrainHeight",
    "GetHeightAt",
}


def test_runtime_hooks_has_no_height_patch_count_cap():
    src = HOOKS.read_text(encoding="utf-8")
    assert "patched >= 4" not in src
    assert "if (patched >= 4)" not in src
    assert "patched >= 6" not in src
    # must use discover-all path
    assert "DiscoverHeightQueryMethods" in src
    assert "HeightQueryPatcher" in src


def test_height_query_patcher_prefers_rwg_concrete():
    src = PATCHER.read_text(encoding="utf-8")
    assert "TerrainGeneratorWithBiomeResource" in src
    assert "PreferredConcreteTypeNames" in src
    # interfaces last
    assert "IsInterface" in src
    assert "TypePatchPriority" in src


def test_chunk_inject_sets_blocks_not_only_density():
    src = INJECT.read_text(encoding="utf-8")
    assert "SetBlock" in src
    assert "FindSetBlock" in src
    assert "terrDirt" in src or "terrainFiller" in src


def _monodis_height_methods() -> list[tuple[str, str]]:
    """Return (declaring_type, method_name) for GetTerrainHeight* on this install."""
    if not GAME_DLL.is_file():
        pytest.skip("Assembly-CSharp.dll not installed")
    if shutil.which("monodis") is None:
        pytest.skip("monodis not available")
    types_out = subprocess.check_output(
        ["monodis", "--typedef", str(GAME_DLL)], text=True, errors="replace"
    )
    methods_out = subprocess.check_output(
        ["monodis", "--method", str(GAME_DLL)], text=True, errors="replace"
    )
    entries: list[tuple[int, str]] = []
    for line in types_out.splitlines():
        m = re.match(r"(\d+):\s+(\S+)\s+\(flist=\d+,\s*mlist=(\d+)", line)
        if m:
            entries.append((int(m.group(3)), m.group(2)))
    entries.sort()

    def type_for(mid: int) -> str:
        best = "?"
        for mlist, name in entries:
            if mlist <= mid:
                best = name
            else:
                break
        return best

    found: list[tuple[str, str]] = []
    for line in methods_out.splitlines():
        mm = re.match(r"(\d+):\s+.*\b(GetTerrainHeight\w*|GetHeightAt)\b", line)
        if not mm:
            continue
        mid = int(mm.group(1))
        name = mm.group(2)
        if name not in HEIGHT_NAMES and not name.startswith("GetTerrainHeight"):
            continue
        found.append((type_for(mid), name))
    return found


def test_live_assembly_has_rwg_and_raw_height_methods():
    """Real 3.0.1 game DLL: concrete generators expose GetTerrainHeightByteAt."""
    found = _monodis_height_methods()
    types = {t for t, _ in found}
    # These are the ones Streamed HostWorld / baked paths actually call
    assert "TerrainGeneratorWithBiomeResource" in types, types
    assert "TerrainFromRaw" in types or "TerrainFromDTM" in types, types
    byte_ats = [(t, n) for t, n in found if n == "GetTerrainHeightByteAt"]
    # skeptic: 4 GetTerrainHeightByteAt across ITerrain + DTM + Raw + BiomeResource
    assert len(byte_ats) >= 4, byte_ats
    concrete_byte = [
        t for t, n in byte_ats if t in PREFERRED or t.startswith("Terrain")
    ]
    assert "TerrainGeneratorWithBiomeResource" in concrete_byte
    # Without a cap of 4 total patches, we can cover all ByteAt + At pairs
    assert len(found) >= 8, f"expected >=8 height methods, got {len(found)}: {found}"


def test_shipped_preferred_list_puts_rwg_first():
    """Parse PreferredConcreteTypeNames from HeightQueryPatcher.cs (shipped order)."""
    src = PATCHER.read_text(encoding="utf-8")
    # array block after PreferredConcreteTypeNames
    m = re.search(
        r"PreferredConcreteTypeNames\s*=\s*\{([^}]+)\}",
        src,
        re.S,
    )
    assert m, "PreferredConcreteTypeNames array missing"
    names = re.findall(r'"([^"]+)"', m.group(1))
    assert names[0] == "TerrainGeneratorWithBiomeResource"
    assert "TerrainFromRaw" in names
    assert "TerrainFromDTM" in names
    # interface must not be preferred concrete
    assert "ITerrainGenerator" not in names
    # TypePatchPriority demotes interfaces
    assert (
        "if (t.IsInterface) return -50" in src.replace(" ", "")
        or "t.IsInterface" in src
    )
