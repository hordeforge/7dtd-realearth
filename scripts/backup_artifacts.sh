#!/usr/bin/env bash
# Backup / restore for RealEarth generated artifacts that git does not track:
#   worlds/            baked GeneratedWorlds (dtm.raw, splat3/4, main.ttw, ...)
#   data/samples/      tile packs (.rte + manifests) and height-test packs
#   data/cache/        Terrarium source tiles (rebuild inputs when offline)
#   viewer/data/       exported viewer/webmod map data
# None of these are reproducible without network sources that may disappear,
# so treat archives produced here as the only local durability net.
#
# Usage:
#   scripts/backup_artifacts.sh backup              # write a verified archive
#   scripts/backup_artifacts.sh list ARCHIVE        # show contents
#   scripts/backup_artifacts.sh restore ARCHIVE     # extract back into the repo
#
# Environment:
#   RE_BACKUP_DIR    archive destination (default <repo>/backups).
#                    IMPORTANT: the default shares the repo disk's failure
#                    domain. Copy archives off-host after each run.
#   RE_FORCE_RESTORE set to 1 to overwrite existing artifacts during restore.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${RE_BACKUP_DIR:-$ROOT/backups}"

ARTIFACT_DIRS=(worlds data/samples data/cache viewer/data)

die() { echo "ERROR: $*" >&2; exit 1; }

usage() {
  grep '^#' "$0" | sed -n '2,20p'
  exit "${1:-0}"
}

present_dirs() {
  local d
  for d in "${ARTIFACT_DIRS[@]}"; do
    if [[ -d "$ROOT/$d" ]]; then
      printf '%s\n' "$d"
    fi
  done
  # Always success: under set -euo pipefail a trailing failed [[ ]] in the loop
  # would otherwise kill the caller of $(present_dirs).
  return 0
}

cmd_backup() {
  mkdir -p "$BACKUP_DIR"
  local stamp
  stamp="$(date +%Y%m%dT%H%M%S)"
  local archive="$BACKUP_DIR/realearth-artifacts-$stamp.tar.gz"
  local dirs
  dirs="$(present_dirs)"
  if [[ -z "$dirs" ]]; then
    die "nothing to back up: no ${ARTIFACT_DIRS[*]} present under $ROOT"
  fi

  echo "Backing up into: $archive"
  # shellcheck disable=SC2086
  tar -C "$ROOT" -czf "$archive" $dirs

  # Integrity gate: a backup whose exit code lies is not a backup. Verify the
  # gzip stream and record the checksum next to the artifact.
  gzip -t "$archive"
  (
    cd "$BACKUP_DIR"
    sha256sum "$(basename "$archive")" >"$(basename "$archive").sha256"
    sha256sum -c "$(basename "$archive").sha256" >/dev/null
  )

  local size
  size="$(du -h "$archive" | cut -f1)"
  echo "OK: $archive ($size, verified)"
  echo "Contents:"
  # shellcheck disable=SC2086
  tar -tzf "$archive" | cut -d/ -f1-2 | sort -u | sed 's/^/  /'
  if [[ "$BACKUP_DIR" == "$ROOT"/backups* ]]; then
    echo "WARNING: archive lives on the same disk as the data it protects." >&2
    echo "Copy it off-host (RE_BACKUP_DIR=/mnt/external ...) or instance loss still loses everything." >&2
  fi
}

cmd_list() {
  local archive="${1:?usage: backup_artifacts.sh list ARCHIVE}"
  [[ -f "$archive" ]] || die "no such archive: $archive"
  tar -tzf "$archive"
}

cmd_restore() {
  local archive="${1:?usage: backup_artifacts.sh restore ARCHIVE}"
  [[ -f "$archive" ]] || die "no such archive: $archive"

  local sum="${archive}.sha256"
  if [[ -f "$sum" ]]; then
    (cd "$(dirname "$archive")" && sha256sum -c "$(basename "$sum")") \
      || die "checksum mismatch: refusing to restore a corrupt archive"
  else
    echo "NOTE: no checksum sidecar for $archive; verifying gzip stream only."
    gzip -t "$archive"
  fi

  # Conflict check per exact artifact dir (data/samples, not its parent data/).
  local listed d conflicts=()
  listed="$(tar -tzf "$archive" | cut -d/ -f1-2 | sort -u)"
  for d in "${ARTIFACT_DIRS[@]}"; do
    if ! grep -qx "$d" <<<"$listed" && ! grep -qx "$d/" <<<"$listed"; then
      continue
    fi
    if [[ -e "$ROOT/$d" ]]; then
      if [[ "${RE_FORCE_RESTORE:-0}" == "1" ]]; then
        echo "Moving existing $d aside (RE_FORCE_RESTORE=1)..."
        mv "$ROOT/$d" "$ROOT/${d}.pre-restore-$(date +%Y%m%dT%H%M%S)"
      else
        conflicts+=("$d")
      fi
    fi
  done
  if (( ${#conflicts[@]} )); then
    die "refusing to overwrite existing ${conflicts[*]}; set RE_FORCE_RESTORE=1 to move them aside first"
  fi

  tar -C "$ROOT" -xzf "$archive"
  echo "OK: restored from $(basename "$archive") into $ROOT"
}

case "${1:-}" in
  backup)  cmd_backup ;;
  list)    shift; cmd_list "$@" ;;
  restore) shift; cmd_restore "$@" ;;
  -h|--help|help|"") usage 0 ;;
  *) die "unknown command: $1 (use backup|list|restore)" ;;
esac
