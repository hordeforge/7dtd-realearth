#!/usr/bin/env python3
"""Write the deterministic release archive for an assembled mod folder.

Companion to scripts/package_zip.sh, which resolves the timestamp origin and
calls this module. Everything that decides the archive bytes lives here:

  - entries added in explicit sorted order (never readdir order)
  - one timestamp on every entry, from RE_ZIP_EPOCH
  - uid/gid 0; permissions 0755 for *.sh, 0644 for everything else
  - fixed deflate level
  - internal root named after ModInfo.xml's <Name> (the game-required mod
    identity), never the on-disk folder name

Sidecars written next to the archive:
  <zip>.sha256          integrity of the exact shipped bytes
  <zip>.buildinfo.txt   tool versions + pinned inputs + timestamp origin,
                        so a faithful rebuild attempt is possible later

Usage: package_zip.py MOD_DIR [ZIP_OUT]
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from shutil import copyfileobj

# Toolchain pins recorded in the buildinfo sidecar.
RECORDED_PINS = (
    "ESBUILD_VERSION",
    "TSC_VERSION",
    "OXLINT_VERSION",
    "OXLINT_TSGOLINT_VERSION",
    "OXLINT_PLUGINS_VERSION",
    "OXLINT_STANDARDS_VERSION",
    "ANTI_SLOP_SHA",
    "THREE_TYPES_VERSION",
    "THREE_VERSION",
    "VNU_VERSION",
)
# ZIP timestamps start here; an older epoch would raise.
ZIP_MIN_EPOCH = 315532800


def _modinfo_value(modinfo: str, tag: str, src: Path) -> str:
    match = re.search(rf'<{tag}[^>]*value="([^"]+)"', modinfo)
    if not match:
        print(f'ERROR: no <{tag} value="..."> in {src}', file=sys.stderr)
        sys.exit(2)
    return match.group(1)


def _tool_version(cmd: str) -> str:
    try:
        out = subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            text=True,
            # Tool banners are UTF-8; the platform default codec would mangle a
            # non-ASCII locale string and, on a C locale, raise on it.
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 else "unavailable"
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return "unavailable"


def _pin_lines(env_path: str) -> list[str]:
    if not env_path or not Path(env_path).is_file():
        return []
    text = Path(env_path).read_text(encoding="utf-8")
    lines = []
    for var in RECORDED_PINS:
        match = re.search(rf'^:{var}:=("?)([^"\n]*)\1\s*$', text, re.M)
        if match:
            lines.append(f"{var}={match.group(2)}")
    return lines


def _archive_entries(src: Path) -> list[Path]:
    entries = sorted(src.rglob("*"))
    # A symlink has no content of its own: skipping it would ship an archive
    # quietly missing a file the mod folder has. Name it instead.
    symlinks = [p.relative_to(src).as_posix() for p in entries if p.is_symlink()]
    if symlinks:
        print("ERROR: symlinks under the mod folder cannot be archived:", file=sys.stderr)
        for rel in symlinks:
            print(f"  {rel}", file=sys.stderr)
        sys.exit(2)
    files = [p for p in entries if p.is_file()]
    if not files:
        print("ERROR: nothing to archive", file=sys.stderr)
        sys.exit(2)
    return files


def _write_zip(
    files: list[Path],
    src: Path,
    root: str,
    dst: Path,
    date_time: tuple[int, int, int, int, int, int],
) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in files:
            rel = p.relative_to(src).as_posix()
            info = zipfile.ZipInfo(f"{root}/{rel}", date_time=date_time)
            mode = 0o755 if rel.endswith(".sh") else 0o644
            info.create_system = 3  # unix: external_attr carries the permission bits
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with zf.open(info, "w") as target, p.open("rb") as handle:
                copyfileobj(handle, target, length=1 << 20)


def main(argv: list[str]) -> int:
    src = Path(argv[1]).resolve()
    modinfo_path = src / "ModInfo.xml"
    modinfo = modinfo_path.read_text(encoding="utf-8")
    root = _modinfo_value(modinfo, "Name", modinfo_path)
    version = _modinfo_value(modinfo, "Version", modinfo_path)
    # Release-archive name follows ModInfo.xml's version (same parse as
    # .github/workflows/release.yml): dist/RealEarth-v0.3.0.zip.
    if len(argv) > 2 and argv[2]:
        dst = Path(argv[2]).resolve()
    else:
        dst = src.parent / f"{src.name}-v{version}.zip"

    epoch = max(int(os.environ["RE_ZIP_EPOCH"]), ZIP_MIN_EPOCH)
    origin = os.environ["RE_ZIP_EPOCH_ORIGIN"]
    year, month, day, hour, minute, second = time.gmtime(epoch)[:6]
    date_time = (year, month, day, hour, minute, second)

    files = _archive_entries(src)
    _write_zip(files, src, root, dst, date_time)

    digest = hashlib.sha256(dst.read_bytes()).hexdigest()
    # Same format as scripts/backup_artifacts.sh: verifiable by sha256sum -c.
    dst.with_name(dst.name + ".sha256").write_text(f"{digest}  {dst.name}\n", encoding="utf-8")

    lines = [
        f"archive={dst.name}",
        f"archive_sha256={digest}",
        f"archive_bytes={dst.stat().st_size}",
        f"mod_name={root}",
        f"source_dir={src.name}",
        f"entry_timestamp={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))}",
        f"entry_timestamp_origin={origin}",
        f"entry_count={len(files)}",
        f"python={_tool_version('python3')}",
        f"dotnet={_tool_version('dotnet')}",
        f"uv={_tool_version('uv')}",
        f"bun={_tool_version('bun')}",
        *_pin_lines(os.environ.get("RE_ZIP_TOOLCHAIN_ENV", "")),
    ]
    buildinfo = dst.with_name(dst.name + ".buildinfo.txt")
    buildinfo.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"realearth: zip -> {dst}")
    print(f"realearth: sha256 {digest}")
    print(f"realearth: buildinfo -> {buildinfo}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ERROR: package_zip.py needs MOD_DIR (and optionally ZIP_OUT)", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv))
