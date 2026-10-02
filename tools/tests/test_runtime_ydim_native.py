"""Run the shipped height transpiler against layer allocation and mask IL."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_layer_initializers_preserve_shift_masks(tmp_path: Path) -> None:
    game = Path(os.environ.get("SEVENDTD_GAME_DIR", ""))
    harmony = game / "Mods/0_TFP_Harmony/0Harmony.dll"
    if not harmony.is_file() or shutil.which("dotnet") is None:
        pytest.skip("native IL check needs dotnet and SEVENDTD_GAME_DIR with Harmony")
    project = Path(__file__).with_name("runtime_ydim_checks.csproj")
    subprocess.run(
        [
            "dotnet",
            "build",
            str(project),
            "--configuration",
            "Release",
            "--output",
            str(tmp_path / "bin"),
            f"-p:BaseIntermediateOutputPath={tmp_path / 'obj'}/",
            f"-p:MSBuildProjectExtensionsPath={tmp_path / 'obj'}/",
            f"-p:GameDir={game}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    result = subprocess.run(
        ["dotnet", str(tmp_path / "bin/runtime_ydim_checks.dll")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "runtime height IL checks passed" in result.stdout
