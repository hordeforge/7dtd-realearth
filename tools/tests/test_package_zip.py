"""Pin scripts/package_zip.sh: deterministic release-archive bytes.

The zip attached to a release must not depend on who ran the build: these
tests drive the shipped script end-to-end on synthetic mod folders and assert
the archive fields that hand-rolled zips leave to the filesystem (entry
order, timestamps, permissions) plus the checksum/buildinfo sidecars.
"""

import hashlib
import os
import subprocess
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "package_zip.sh"

MODINFO = """<?xml version="1.0" encoding="UTF-8" ?>
<xml>
  <Name value="RealEarth" />
  <Version value="9.9.9" />
</xml>
"""


def make_mod(root: Path) -> Path:
    mod = root / "RealEarth"
    (mod / "Config").mkdir(parents=True)
    (mod / "Tools").mkdir()
    (mod / "ModInfo.xml").write_text(MODINFO, encoding="utf-8")
    (mod / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (mod / "Config" / "realearth.json").write_text("k: v\n", encoding="utf-8")
    (mod / "Tools" / "run.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    return mod


def run_zip(mod: Path, out_dir: Path, extra_env: dict[str, str]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("SOURCE_DATE_EPOCH", None)
    env.update(extra_env)
    subprocess.run(
        ["bash", str(SCRIPT), str(mod), str(out_dir / "out.zip")],
        check=True,
        env=env,
    )
    return out_dir / "out.zip"


def test_deterministic_across_paths_times_and_locale(tmp_path) -> None:
    """Same source, different folder/path/locale/wall-time: identical bytes."""
    first_mod = make_mod(tmp_path / "a")
    second_mod = make_mod(tmp_path / "b" / "deeper" / "renamed")
    # Identical committed-state timestamps (the no-git fallback input), but
    # everything else drifts, as it would across two checkouts.
    for mod in (first_mod, second_mod):
        os.utime(mod / "ModInfo.xml", (1700000000, 1700000000))
    os.utime(second_mod / "LICENSE", (1600000000, 1600000000))
    os.utime(first_mod / "LICENSE", (1500000000, 1500000000))

    first = run_zip(
        first_mod,
        tmp_path / "run1",
        {"TZ": "UTC", "LC_ALL": "C"},
    )
    second = run_zip(
        second_mod,
        tmp_path / "run2",
        {"TZ": "Pacific/Kiritimati", "LC_ALL": "C.UTF-8"},
    )
    assert first.read_bytes() == second.read_bytes()


def test_source_date_epoch_pins_every_entry_timestamp(tmp_path) -> None:
    mod = make_mod(tmp_path / "RealEarth")
    archive = run_zip(
        mod,
        tmp_path / "run",
        {"SOURCE_DATE_EPOCH": "1700000000", "TZ": "Asia/Tokyo"},
    )
    with zipfile.ZipFile(archive) as zf:
        stamps = {info.date_time for info in zf.infolist()}
    # 1700000000 = 2023-11-14T22:13:20Z
    assert stamps == {(2023, 11, 14, 22, 13, 20)}


def test_sorted_entries_canonical_root_and_permissions(tmp_path) -> None:
    mod = make_mod(tmp_path / "assembled_elsewhere")
    archive = run_zip(mod, tmp_path / "run", {})
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
    names = [i.filename for i in infos]
    assert names == sorted(names)
    assert all(n.startswith("RealEarth/") for n in names), names
    modes = {i.filename: i.external_attr >> 16 for i in infos}
    assert modes["RealEarth/ModInfo.xml"] & 0o777 == 0o644
    assert modes["RealEarth/Tools/run.sh"] & 0o777 == 0o755


def test_sidecars_record_checksum_and_build_environment(tmp_path) -> None:
    mod = make_mod(tmp_path / "RealEarth")
    out_dir = tmp_path / "run"
    archive = run_zip(mod, out_dir, {})
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    sha_line = (out_dir / "out.zip.sha256").read_text(encoding="utf-8").split()
    assert sha_line[0] == digest

    buildinfo = (out_dir / "out.zip.buildinfo.txt").read_text(encoding="utf-8")
    assert f"archive_sha256={digest}" in buildinfo
    assert "entry_timestamp_origin=" in buildinfo
    assert "python=" in buildinfo


def test_refuses_folder_without_modinfo(tmp_path) -> None:
    bare = tmp_path / "not-a-mod"
    bare.mkdir()
    result = subprocess.run(
        ["bash", str(SCRIPT), str(bare), str(tmp_path / "out.zip")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "ModInfo.xml" in result.stderr
