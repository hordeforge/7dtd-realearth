#!/usr/bin/env bash
# Zip an assembled mod folder deterministically.
#
# `make package` assembles dist/RealEarth/ via package_mod.sh. The zip a
# release attaches must not depend on who ran the build: zipping by hand
# embeds the maintainer's file mtimes, uid/gid, and directory-listing order,
# so two builds of the same source never agree byte-for-byte. This script
# normalizes every archive field:
#
#   - entries added in explicit sorted order (never readdir order)
#   - one timestamp on every entry: SOURCE_DATE_EPOCH when set, else the git
#     commit date of ModInfo.xml (identical for any checkout of the same
#     source), else the file's mtime as a last resort
#   - uid/gid 0; permissions 0755 for *.sh, 0644 for everything else
#   - fixed deflate level
#   - internal root named after ModInfo.xml's <Name> (the game-required mod
#     identity), never the on-disk folder name, so the archive bytes do not
#     depend on where or under what name the folder was assembled
#
# Sidecars written next to the archive:
#   <zip>.sha256          integrity of the exact shipped bytes
#   <zip>.buildinfo.txt   tool versions + pinned inputs + timestamp origin,
#                         so a faithful rebuild attempt is possible later
#
# Usage: scripts/package_zip.sh MOD_DIR [ZIP_OUT]

set -euo pipefail

DIR="${1:?usage: package_zip.sh MOD_DIR [ZIP_OUT]}"
if [[ ! -d "$DIR" ]]; then
  echo "ERROR: not a directory: $DIR" >&2
  exit 2
fi
if [[ ! -f "$DIR/ModInfo.xml" ]]; then
  echo "ERROR: no ModInfo.xml under $DIR (pass the assembled mod folder)" >&2
  exit 2
fi
if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 is required to write the deterministic zip" >&2
  exit 2
fi

# Timestamp origin, most stable first. Exported for the python payload below.
EPOCH=""
ORIGIN=""
if [[ -n "${SOURCE_DATE_EPOCH:-}" ]]; then
  EPOCH="$SOURCE_DATE_EPOCH"
  ORIGIN="SOURCE_DATE_EPOCH"
else
  EPOCH="$(git -C "$DIR" log -1 --format=%ct -- ModInfo.xml 2>/dev/null || true)"
  ORIGIN="git commit date of ModInfo.xml"
fi
case "$EPOCH" in
  "" | *[!0-9]*) EPOCH="$(stat -c %Y "$DIR/ModInfo.xml")"; ORIGIN="ModInfo.xml mtime" ;;
esac
export RE_ZIP_EPOCH="$EPOCH" RE_ZIP_EPOCH_ORIGIN="$ORIGIN"

# Pinned JS toolchain versions for the buildinfo record (best effort: the
# sidecar documents what built this tree, it must not fail the packaging).
TOOLCHAIN_ENV="$(cd "$(dirname "$0")" && pwd)/toolchain-versions.env"
export RE_ZIP_TOOLCHAIN_ENV="$TOOLCHAIN_ENV"

OUT="${2:-$(dirname "$DIR")/$(basename "$DIR").zip}"

# Release-archive name follows ModInfo.xml's version (same parse as
# .github/workflows/release.yml): dist/RealEarth-v0.3.0.zip.
VERSION="$(sed -n 's/.*<Version[^>]*value="\([^"]*\)".*/\1/p' "$DIR/ModInfo.xml" | head -1)"
OUT="${2:-$(dirname "$DIR")/$(basename "$DIR")${VERSION:+-v$VERSION}.zip}"

python3 - "$DIR" "$OUT" <<'PY'
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

src = Path(sys.argv[1]).resolve()
dst = Path(sys.argv[2]).resolve()

modinfo = (src / "ModInfo.xml").read_text(encoding="utf-8")
name_match = re.search(r'<Name[^>]*value="([^"]+)"', modinfo)
if not name_match:
    print("ERROR: no <Name value=\"...\"> in ModInfo.xml", file=sys.stderr)
    sys.exit(2)
root = name_match.group(1)

epoch = int(os.environ["RE_ZIP_EPOCH"])
origin = os.environ["RE_ZIP_EPOCH_ORIGIN"]
# ZIP timestamps start at 1980; older epochs would raise.
epoch = max(epoch, 315532800)
date_time = time.gmtime(epoch)[:6]


def tool_version(cmd: str) -> str:
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=20)
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 else "unavailable"
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"


files = sorted(
    p for p in src.rglob("*")
    if p.is_file() and not p.is_symlink()
)
if not files:
    print("ERROR: nothing to archive", file=sys.stderr)
    sys.exit(2)

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

digest = hashlib.sha256(dst.read_bytes()).hexdigest()
# Same format as scripts/backup_artifacts.sh: verifiable by sha256sum -c.
dst.with_name(dst.name + ".sha256").write_text(f"{digest}  {dst.name}\n", encoding="utf-8")

buildinfo = dst.with_name(dst.name + ".buildinfo.txt")
env_lines = []
for var in (
    "ESBUILD_VERSION", "TSC_VERSION", "OXLINT_VERSION", "OXLINT_TSGOLINT_VERSION",
    "OXLINT_PLUGINS_VERSION", "OXLINT_STANDARDS_VERSION", "ANTI_SLOP_SHA",
    "THREE_TYPES_VERSION", "THREE_VERSION", "VNU_VERSION",
):
    env_path = os.environ.get("RE_ZIP_TOOLCHAIN_ENV", "")
    if env_path and Path(env_path).is_file():
        import re
        match = re.search(rf'^:{var}:=("?)([^"\n]*)\1\s*$', Path(env_path).read_text(encoding="utf-8"), re.M)
        if match:
            env_lines.append(f"{var}={match.group(2)}")

lines = [
    f"archive={dst.name}",
    f"archive_sha256={digest}",
    f"archive_bytes={dst.stat().st_size}",
    f"mod_name={root}",
    f"source_dir={src.name}",
    f"entry_timestamp={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))}",
    f"entry_timestamp_origin={origin}",
    f"entry_count={len(files)}",
    f"python={tool_version('python3')}",
    f"dotnet={tool_version('dotnet')}",
    f"uv={tool_version('uv')}",
    f"bun={tool_version('bun')}",
    *env_lines,
]
buildinfo.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"realearth: zip -> {dst}")
print(f"realearth: sha256 {digest}")
print(f"realearth: buildinfo -> {buildinfo}")
PY
