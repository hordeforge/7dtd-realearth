#!/usr/bin/env bash
# Zip an assembled mod folder deterministically.
#
# `make package` assembles dist/RealEarth/ via package_mod.sh. The zip a
# release attaches must not depend on who ran the build: zipping by hand
# embeds the maintainer's file mtimes, uid/gid, and directory-listing order,
# so two builds of the same source never agree byte-for-byte. This script
# resolves the timestamp origin and hands the folder to package_zip.py, which
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

usage() {
  # Header comment, '# ' stripped; a fixed line range would shift whenever a
  # note is added above it.
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac
if [[ $# -lt 1 ]]; then
  echo "ERROR: package_zip.sh needs MOD_DIR (and optionally ZIP_OUT)" >&2
  usage >&2
  exit 2
fi

DIR="$1"
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
script_dir="$(cd "$(dirname "$0")" && pwd)"
export RE_ZIP_TOOLCHAIN_ENV="$script_dir/toolchain-versions.env"

# The archive bytes (entry order, timestamps, permissions, sidecars) are
# written by package_zip.py, the same way scripts/sbom.py owns the SPDX
# inventory: shell resolves the environment, python owns the format. An
# omitted ZIP_OUT leaves the name to python (ModInfo.xml <Version>).
if [[ $# -ge 2 ]]; then
  exec python3 "$script_dir/package_zip.py" "$DIR" "$2"
fi
exec python3 "$script_dir/package_zip.py" "$DIR"
