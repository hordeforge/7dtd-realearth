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
#   scripts/backup_artifacts.sh status              # freshness / off-host check
#
# Environment:
#   RE_BACKUP_DIR    archive destination (default <repo>/backups).
#                    IMPORTANT: the default shares the repo disk's failure
#                    domain. Copy archives off-host after each run.
#   RE_BACKUP_MAX_AGE_DAYS  status fails when the newest archive is older
#                    (default 7). Nothing schedules a backup, so freshness is
#                    only ever asserted by asking.
#   RE_BACKUP_KEEP   keep only the newest N archives (default 0 = keep all);
#                    older archives and their sidecars are pruned after the
#                    new archive is verified, never before.
#   RE_BACKUP_EXTRA_PATHS
#                    newline-separated label=/absolute/path entries for state
#                    that lives outside the repo (dedicated-server saves,
#                    installed GeneratedWorlds, install trash). Each is stored
#                    under realearth-extra/<label>/ with the absolute target
#                    recorded beside it, and restored back to that path. A
#                    path that does not exist fails the backup rather than
#                    being silently omitted.
#   RE_FORCE_RESTORE set to 1 to overwrite existing artifacts during restore.
#   RE_ROOT         operate on this tree instead of the repo (used by the
#                   artifacts-drill sandbox; never point it at anything else).
set -euo pipefail

ROOT="${RE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
BACKUP_DIR="${RE_BACKUP_DIR:-$ROOT/backups}"
MAX_AGE_DAYS="${RE_BACKUP_MAX_AGE_DAYS:-7}"
KEEP="${RE_BACKUP_KEEP:-0}"

ARTIFACT_DIRS=(worlds data/samples data/cache viewer/data)

# Archive prefix for out-of-tree state, and the manifest file recording where
# each of those trees came from.
EXTRA_PREFIX=realearth-extra
TARGET_FILE=.realearth-target

# Inventory member inside every archive: which ARTIFACT_DIRS were in it, which
# were absent when it was written, and every out-of-tree target. Without it a
# restore of an archive that never contained data/cache/ is indistinguishable
# from a complete one, which is the narrowing this script exists to prevent.
# Only the tree shape is recorded (no stamp, no host, no paths outside the
# extras), so an unchanged tree still produces identical manifest bytes.
MANIFEST_NAME=realearth-backup-manifest.txt
MANIFEST_SCHEMA=1
EXTRA_SPEC="${RE_BACKUP_EXTRA_PATHS:-}"
EXTRA_LABELS=()
EXTRA_PATHS=()

die() { echo "ERROR: $*" >&2; exit 1; }

usage() {
  # Print this file's header comment (everything between the shebang and the
  # first code line) with the leading '# ' stripped. A fixed line range would
  # shift or truncate the help the next time a note is added above it.
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

usage_error() {
  usage >&2
  exit 2
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

# Parse RE_BACKUP_EXTRA_PATHS into EXTRA_LABELS/EXTRA_PATHS. Every entry is
# validated up front: a typo that silently dropped a save directory would
# leave an archive that claims to be complete and is not.
load_extras() {
  [[ -n "${EXTRA_SPEC//[[:space:]]/}" ]] || return 0
  local line label path
  while IFS= read -r line; do
    [[ -n "${line//[[:space:]]/}" ]] || continue
    [[ "$line" == *=* ]] ||
      die "RE_BACKUP_EXTRA_PATHS entry needs label=/absolute/path (got: $line)"
    label="${line%%=*}"
    path="${line#*=}"
    [[ "$label" =~ ^[A-Za-z0-9._-]+$ ]] ||
      die "RE_BACKUP_EXTRA_PATHS label must match [A-Za-z0-9._-]+ (got: $label)"
    [[ "$path" == /* ]] ||
      die "RE_BACKUP_EXTRA_PATHS path must be absolute (got: $path)"
    [[ -e "$path" ]] ||
      die "RE_BACKUP_EXTRA_PATHS path does not exist: $path"
    case " ${EXTRA_LABELS[*]:-} " in
      *" $label "*) die "duplicate RE_BACKUP_EXTRA_PATHS label: $label" ;;
    esac
    EXTRA_LABELS+=("$label")
    EXTRA_PATHS+=("$path")
  done <<<"$EXTRA_SPEC"
}

# Build the staging tree the extra entries are archived from: a per-label
# directory holding the recorded target path and a symlink to the real tree.
stage_extras() {
  local stage="$1" i
  for i in "${!EXTRA_LABELS[@]}"; do
    mkdir -p "$stage/$EXTRA_PREFIX/${EXTRA_LABELS[$i]}"
    printf '%s\n' "${EXTRA_PATHS[$i]}" \
      >"$stage/$EXTRA_PREFIX/${EXTRA_LABELS[$i]}/$TARGET_FILE"
    ln -s "${EXTRA_PATHS[$i]}" "$stage/$EXTRA_PREFIX/${EXTRA_LABELS[$i]}/data"
  done
}

# Record what went into the archive. Deterministic on purpose: the same tree
# and the same RE_BACKUP_EXTRA_PATHS must yield the same manifest, so an
# unchanged backup is still byte-comparable. The run's stamp and host go in a
# .meta sidecar instead, which restore does not need.
write_manifest() {
  local stage="$1" dirs="$2" d
  {
    echo "realearth-artifact-manifest $MANIFEST_SCHEMA"
    echo "included:${dirs:+ ${dirs//$'\n'/ }}"
    for d in "${ARTIFACT_DIRS[@]}"; do
      [[ -d "$ROOT/$d" ]] || echo "absent: $d"
    done
    local i
    for i in "${!EXTRA_LABELS[@]}"; do
      echo "extra: ${EXTRA_LABELS[$i]}=${EXTRA_PATHS[$i]}"
    done
  } >"$stage/$MANIFEST_NAME"
}

# Drop archives older than the newest KEEP. Runs only after the new archive
# passed its checksum gate, so a failed backup never prunes the last good one.
prune_old_archives() {
  (( KEEP > 0 )) || return 0
  local -a old=()
  local f
  while IFS= read -r f; do
    [[ -n "$f" ]] && old+=("$f")
  done < <(
    find "$BACKUP_DIR" -maxdepth 1 -type f -name 'realearth-artifacts-*.tar.gz' \
      -printf '%T@ %p\n' | sort -rn | tail -n "+$((KEEP + 1))" | cut -d' ' -f2-
  )
  ((${#old[@]})) || return 0
  for f in "${old[@]}"; do
    rm -f -- "$f" "$f.sha256" "$f.meta"
    echo "Pruned old archive: $(basename "$f")"
  done
}

cmd_backup() {
  mkdir -p "$BACKUP_DIR"
  local stamp
  # UTC stamp: a fall-back DST hour would repeat a local stamp and tar would
  # silently overwrite the earlier archive; UTC is unique and sorts by creation.
  stamp="$(date -u +%Y%m%dT%H%M%S)"
  local archive="$BACKUP_DIR/realearth-artifacts-$stamp.tar.gz"
  # The stamp resolves to one second; a second backup inside that same second
  # would otherwise overwrite the earlier archive and destroy a durable copy.
  # Bump a suffix until the name is free so every backup run is its own artifact.
  local n=1
  while [[ -e "$archive" ]]; do
    archive="$BACKUP_DIR/realearth-artifacts-$stamp.$n.tar.gz"
    n=$((n + 1))
  done
  local dirs
  dirs="$(present_dirs)"
  case "$KEEP" in
    ""|*[!0-9]*)
      echo "ERROR: RE_BACKUP_KEEP must be a non-negative integer (got: $KEEP)" >&2
      exit 2
      ;;
  esac
  load_extras
  if [[ -z "$dirs" ]] && ((${#EXTRA_LABELS[@]} == 0)); then
    die "nothing to back up: no ${ARTIFACT_DIRS[*]} present under $ROOT and no extra paths"
  fi

  echo "Backing up into: $archive"
  # Member order, uid/gid and the gzip header are normalized (gzip -n), so
  # backing up an unchanged tree twice produces the same bytes and a differing
  # sha256 means new data rather than a re-run. File mtimes are kept as they
  # are: the terrarium cache and packed tiles are reused by age.
  partial="$archive.partial"
  # Uncompressed staging file: the out-of-tree entries are appended to it
  # before the single normalized gzip pass, so the extras and the artifact
  # dirs end up in one archive.
  partial_tar="$archive.partial.tar"
  # --sort/--owner are GNU tar options (bsdtar, which macOS ships as tar, has
  # neither): fall back to a plain archive there rather than failing the
  # backup, and say so, because only the normalized form is byte-comparable.
  tar_opts=()
  if tar --help 2>&1 | grep -q -- '--sort'; then
    tar_opts=(--sort=name --owner=0 --group=0 --numeric-owner)
  else
    echo "NOTE: this tar has no --sort/--owner (not GNU tar); the archive is not byte-comparable." >&2
  fi
  # With no artifact dir present, an empty archive is the right result (the
  # extra paths still have a stage to add below); feed tar an empty member
  # list instead of letting it refuse to create one.
  empty_list=()
  if [[ -z "$dirs" ]]; then
    empty_list=(--files-from /dev/null)
  fi
  # ${arr[@]+"${arr[@]}"} keeps the empty case legal under set -u on bash 3.2.
  # shellcheck disable=SC2086 # $dirs is a space-separated path list; tar_opts
  # and empty_list must word-split into separate options.
  if ! tar -C "$ROOT" ${tar_opts[@]+"${tar_opts[@]}"} ${empty_list[@]+"${empty_list[@]}"} -cf "$partial_tar" $dirs; then
    rm -f "$partial_tar"
    die "tar failed while writing $archive"
  fi

  # Out-of-tree state goes in under EXTRA_PREFIX, and the inventory manifest
  # alongside it. -h is scoped to the extras invocation so it follows only the
  # stage's own symlinks; symlinks already inside the artifact dirs keep
  # archiving as links, as the create step did. The append targets the
  # uncompressed staging file: a second gzip -czf on the archive would
  # truncate the first one, and two concatenated gzip members lose all but
  # the first when read back.
  local stage extra_args=()
  stage="$(mktemp -d "$BACKUP_DIR/.stage-$stamp.XXXXXX")"
  if ((${#EXTRA_LABELS[@]})); then
    stage_extras "$stage"
    extra_args+=("$EXTRA_PREFIX")
  fi
  write_manifest "$stage" "$dirs"
  extra_args+=("$MANIFEST_NAME")
  # -f takes the archive as the next argument. extra_args are members, so the
  # staging tar has to come first or tar treats the manifest name as the archive.
  if ! tar -C "$stage" -rhf "$partial_tar" "${extra_args[@]}"; then
    rm -rf "$stage"
    rm -f "$partial_tar"
    die "tar failed while writing $archive"
  fi
  rm -rf "$stage"

  if ! gzip -n -9 -c "$partial_tar" >"$partial"; then
    rm -f "$partial" "$partial_tar"
    die "gzip failed while writing $archive"
  fi
  rm -f "$partial_tar"
  mv "$partial" "$archive"

  # Integrity gate: a backup whose exit code lies is not a backup. Verify the
  # gzip stream and record the checksum next to the artifact.
  gzip -t "$archive"
  (
    cd "$BACKUP_DIR"
    sha256sum "$(basename "$archive")" >"$(basename "$archive").sha256"
    sha256sum -c "$(basename "$archive").sha256" >/dev/null
  )
  # Provenance of the run. Not needed to restore, so it stays a sidecar: only
  # the .sha256 is a restore prerequisite.
  {
    echo "created_utc=$stamp"
    echo "host=$(hostname 2>/dev/null || echo unknown)"
    echo "root=$ROOT"
    echo "archive=$(basename "$archive")"
  } >"${archive}.meta"

  local size
  size="$(du -h "$archive" | cut -f1)"
  echo "OK: $archive ($size, verified)"
  echo "Contents:"
  # shellcheck disable=SC2086 # same path-list split as the tar call above.
  tar -tzf "$archive" | cut -d/ -f1-2 | sort -u | sed 's/^/  /'
  if [[ "$BACKUP_DIR" == "$ROOT"/backups* ]]; then
    echo "WARNING: archive lives on the same disk as the data it protects." >&2
    echo "Copy it off-host (RE_BACKUP_DIR=/mnt/external ...) or instance loss still loses everything." >&2
  fi
  # An artifact dir that does not exist right now is not in this archive, and
  # a restore months later cannot tell that from a directory that was empty.
  local d
  for d in "${ARTIFACT_DIRS[@]}"; do
    [[ -d "$ROOT/$d" ]] || \
      echo "WARNING: $d does not exist; it is NOT in this archive." >&2
  done
  # Save games are the one irreplaceable state, and they live outside the
  # repo. An archive that does not name them says so on every run.
  if ((${#EXTRA_LABELS[@]} == 0)); then
    echo "WARNING: no RE_BACKUP_EXTRA_PATHS; dedicated-server save games are" >&2
    echo "NOT in this archive (name them: RE_BACKUP_EXTRA_PATHS=\"saves=\$USERDATA/Saves\")." >&2
  fi

  # The terrarium cache is the only local copy of source tiles; if it was
  # relocated via RE_TERRARIUM_CACHE this archive does not contain it.
  local tcache="${RE_TERRARIUM_CACHE:-}"
  if [[ -n "$tcache" && -d "$tcache" && "$tcache" != "$ROOT"/data/cache/* ]]; then
    echo "WARNING: RE_TERRARIUM_CACHE=$tcache is outside data/cache;" >&2
    echo "the source-tile cache is NOT in this archive. Copy it into your off-host set manually." >&2
  fi
  if ((${#EXTRA_LABELS[@]})); then
    echo "Out-of-tree trees archived:"
    local i
    for i in "${!EXTRA_LABELS[@]}"; do
      echo "  ${EXTRA_LABELS[$i]} -> ${EXTRA_PATHS[$i]}"
    done
  fi

  # Only now that a verified archive exists is it safe to drop older ones.
  prune_old_archives
}

cmd_list() {
  [[ $# -ge 1 ]] || { echo "ERROR: list needs an ARCHIVE" >&2; usage_error; }
  local archive="$1"
  [[ -f "$archive" ]] || die "no such archive: $archive"
  tar -tzf "$archive"
}

# Report whether a fresh, verified archive exists. Nothing schedules a backup,
# so "the last run exited 0" is the only evidence an operator ever gets; this
# answers the question that actually matters after a bake or a disk scare.
cmd_status() {
  local rc=0 newest age_days now
  case "$MAX_AGE_DAYS" in
    ""|*[!0-9]*)
      echo "ERROR: RE_BACKUP_MAX_AGE_DAYS must be a non-negative integer (got: $MAX_AGE_DAYS)" >&2
      exit 2
      ;;
  esac
  if [[ ! -d "$BACKUP_DIR" ]]; then
    echo "NO BACKUP: $BACKUP_DIR does not exist; run scripts/backup_artifacts.sh backup" >&2
    return 1
  fi
  newest="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'realearth-artifacts-*.tar.gz' \
    -printf '%T@ %p\n' | sort -rn | head -n1 | cut -d' ' -f2-)"
  if [[ -z "$newest" ]]; then
    echo "NO BACKUP: no realearth-artifacts-*.tar.gz under $BACKUP_DIR" >&2
    return 1
  fi
  now="$(date -u +%s)"
  age_days=$(( (now - $(stat -c %Y "$newest")) / 86400 ))
  if (( age_days > MAX_AGE_DAYS )); then
    echo "STALE: newest archive $newest is ${age_days}d old (limit ${MAX_AGE_DAYS}d)" >&2
    rc=1
  else
    echo "fresh: $newest (${age_days}d old, limit ${MAX_AGE_DAYS}d)"
  fi
  if [[ -f "${newest}.sha256" ]]; then
    if ! (cd "$(dirname "$newest")" && sha256sum -c "$(basename "${newest}.sha256")" >/dev/null); then
      echo "CORRUPT: checksum mismatch on $newest" >&2
      rc=1
    fi
  else
    echo "CORRUPT: no .sha256 sidecar for $newest" >&2
    rc=1
  fi
  if [[ "$BACKUP_DIR" == "$ROOT"/backups* ]]; then
    echo "SAME-DISK: $BACKUP_DIR shares the repo disk; instance loss takes the archives too" >&2
  fi
  return "$rc"
}

cmd_restore() {
  [[ $# -ge 1 ]] || { echo "ERROR: restore needs an ARCHIVE" >&2; usage_error; }
  local archive="$1"
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
  # Out-of-tree targets are checked first and collect-only, so a bad extra
  # target aborts before any existing tree has been moved aside.
  local listed d conflicts=()
  local members=() member
  mapfile -t members < <(tar -tzf "$archive" | grep "^$EXTRA_PREFIX/") || true

  if ((${#members[@]})); then
    [[ ! -e "$ROOT/$EXTRA_PREFIX" ]] ||
      die "refusing to overwrite existing $ROOT/$EXTRA_PREFIX; move it aside first"
    for member in "${members[@]}"; do
      [[ "$member" == "$EXTRA_PREFIX"/*/"$TARGET_FILE" ]] || continue
      local target
      target="$(tar -xzOf "$archive" "$member")"
      [[ -n "$target" ]] ||
        die "extra tree $(dirname "$member") records no target path"
      if [[ -e "$target" && "${RE_FORCE_RESTORE:-0}" != "1" ]]; then
        conflicts+=("$target")
      fi
    done
  fi

  listed="$(tar -tzf "$archive" | cut -d/ -f1-2 | sort -u)"
  for d in "${ARTIFACT_DIRS[@]}"; do
    if ! grep -qx "$d" <<<"$listed" && ! grep -qx "$d/" <<<"$listed"; then
      continue
    fi
    if [[ -e "$ROOT/$d" ]]; then
      if [[ "${RE_FORCE_RESTORE:-0}" == "1" ]]; then
        echo "Moving existing $d aside (RE_FORCE_RESTORE=1)..."
        local aside
        aside="$ROOT/${d}.pre-restore-$(date -u +%Y%m%dT%H%M%S)"
        local m=1
        while [[ -e "$aside" ]]; do
          aside="$ROOT/${d}.pre-restore-$(date -u +%Y%m%dT%H%M%S).$m"
          m=$((m + 1))
        done
        mv "$ROOT/$d" "$aside"
      else
        conflicts+=("$d")
      fi
    fi
  done
  if (( ${#conflicts[@]} )); then
    die "refusing to overwrite existing ${conflicts[*]}; set RE_FORCE_RESTORE=1 to move them aside first"
  fi

  # The out-of-tree target is known-good to replace by this point.
  for member in "${members[@]}"; do
    [[ "$member" == "$EXTRA_PREFIX"/*/"$TARGET_FILE" ]] || continue
    local target
    target="$(tar -xzOf "$archive" "$member")"
    if [[ -e "$target" ]]; then
      echo "Moving existing $target aside (RE_FORCE_RESTORE=1)..."
      local aside m=1
      aside="$target.pre-restore-$(date -u +%Y%m%dT%H%M%S)"
      while [[ -e "$aside" ]]; do
        aside="$target.pre-restore-$(date -u +%Y%m%dT%H%M%S).$m"
        m=$((m + 1))
      done
      mv "$target" "$aside"
    fi
  done

  tar -C "$ROOT" -xzf "$archive"
  if ((${#members[@]})); then
    for member in "${members[@]}"; do
      [[ "$member" == "$EXTRA_PREFIX"/*/"$TARGET_FILE" ]] || continue
      local label target
      label="$(basename "$(dirname "$member")")"
      target="$(tar -xzOf "$archive" "$member")"
      mkdir -p "$(dirname "$target")"
      mv "$ROOT/$EXTRA_PREFIX/$label/data" "$target"
      echo "  restored $label -> $target"
    done
    rm -rf "${ROOT:?}/$EXTRA_PREFIX"
  fi
  echo "OK: restored from $(basename "$archive") into $ROOT"
}

case "${1:-}" in
  backup)  cmd_backup ;;
  list)    shift; cmd_list "$@" ;;
  restore) shift; cmd_restore "$@" ;;
  status)  cmd_status ;;
  -h|--help|help|"") usage ;;
  # 2, not 1: a mistyped command is a usage error, and scripts branch on that.
  *) echo "ERROR: unknown command: $1 (use backup|list|restore|status)" >&2; usage_error ;;
esac
