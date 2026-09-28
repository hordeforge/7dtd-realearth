#!/usr/bin/env bash
# Prove the artifact backup/restore roundtrip instead of trusting job exit
# codes. Builds a sandbox tree shaped like real state (worlds/, tile pack,
# terrarium cache, viewer exports), backs it up via backup_artifacts.sh,
# destroys the artifacts, restores them, and compares every file byte-for-
# byte. Also asserts the guardrails hold when it matters: an existing tree
# is never clobbered without RE_FORCE_RESTORE=1, a forced restore moves the
# old tree aside instead of deleting it, and a corrupt archive is refused.
#
# Runs entirely inside a sandbox (RE_ROOT override) and removes it on exit;
# the repo and any real artifacts are never touched. The sandbox lives under
# the repo's git-ignored .scratch/, not TMPDIR: /tmp is tmpfs on most Linux
# hosts, so a drill that copies worlds there spends RAM. Set RE_SCRATCH to
# point at a different disk-backed directory.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRATCH_BASE="${RE_SCRATCH:-$HERE/../.scratch}"
mkdir -p "$SCRATCH_BASE"
SANDBOX="$(mktemp -d "$SCRATCH_BASE/realearth-drill.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT

fail() { echo "DRILL FAILED: $*" >&2; exit 1; }

echo "drill: sandbox $SANDBOX"

# --- synthetic artifact state ---
mkdir -p "$SANDBOX/worlds/DrillWorld" \
  "$SANDBOX/data/samples/drill_pack" \
  "$SANDBOX/data/cache/terrarium/0/0" \
  "$SANDBOX/viewer/data"
head -c 65536 /dev/urandom >"$SANDBOX/worlds/DrillWorld/dtm.raw"
printf 'ttw' >"$SANDBOX/worlds/DrillWorld/main.ttw"
head -c 4096 /dev/urandom >"$SANDBOX/data/samples/drill_pack/tile.rte"
head -c 2048 /dev/urandom >"$SANDBOX/data/cache/terrarium/0/0/000.png"
head -c 512 /dev/urandom >"$SANDBOX/viewer/data/export.json"
(
  cd "$SANDBOX"
  find worlds data viewer -type f -print0 | sort -z |
    xargs -0 sha256sum >before.sha256
)

# --- backup: must produce a verified archive covering all four dirs ---
# The sandbox carries its own cache; an exported RE_TERRARIUM_CACHE pointing
# at the real repo would only trip the outside-data/cache warning.
RE_ROOT="$SANDBOX" RE_TERRARIUM_CACHE='' "$HERE/backup_artifacts.sh" backup >/dev/null ||
  fail "backup step exited nonzero"
archive="$(find "$SANDBOX/backups" -name 'realearth-artifacts-*.tar.gz' | head -n1)"
[[ -n "$archive" ]] || fail "no realearth-artifacts-*.tar.gz written"
[[ -f "${archive}.sha256" ]] || fail "checksum sidecar missing next to archive"
for d in worlds data/samples data/cache viewer/data; do
  grep -q "^$d/" <(tar -tzf "$archive") ||
    fail "archive does not contain $d"
done
RE_ROOT="$SANDBOX" "$HERE/backup_artifacts.sh" list "$archive" >/dev/null ||
  fail "list step exited nonzero"
echo "drill: backup + list ok ($(basename "$archive"))"

# --- status must fail when there is no backup, and on a tampered archive ---
if RE_ROOT="$SANDBOX" RE_BACKUP_DIR="$SANDBOX/no-archives" \
  "$HERE/backup_artifacts.sh" status >/dev/null 2>&1; then
  fail "status passed with no archive at all"
fi
RE_ROOT="$SANDBOX" "$HERE/backup_artifacts.sh" status >/dev/null 2>&1 ||
  fail "status failed on a fresh verified archive"
orig_size="$(stat -c %s "$archive")"
printf 'tamper' >>"$archive"
if RE_ROOT="$SANDBOX" "$HERE/backup_artifacts.sh" status >/dev/null 2>&1; then
  fail "status passed on an archive whose checksum no longer matches"
fi
# Undo the tamper so the restore steps below still use the original bytes.
truncate -s "$orig_size" "$archive"
RE_ROOT="$SANDBOX" "$HERE/backup_artifacts.sh" status >/dev/null 2>&1 ||
  fail "status failed after the tampered bytes were removed"
echo "drill: status rejects missing and tampered archives"

# --- destroy everything, then try restore against a conflicting tree ---
rm -rf "$SANDBOX/worlds" "$SANDBOX/data/samples" "$SANDBOX/data/cache" \
  "$SANDBOX/data/cache" "$SANDBOX/viewer/data"
mkdir -p "$SANDBOX/worlds/DrillWorld"
head -c 128 /dev/urandom >"$SANDBOX/worlds/DrillWorld/operator-junk.bin"

if RE_ROOT="$SANDBOX" "$HERE/backup_artifacts.sh" restore "$archive" >/dev/null 2>&1; then
  fail "restore overwrote an existing tree without RE_FORCE_RESTORE=1"
fi
[[ -f "$SANDBOX/worlds/DrillWorld/operator-junk.bin" ]] ||
  fail "refused restore still touched existing files"
echo "drill: clobber refused, existing tree untouched"

# --- forced restore: old tree moves aside, archive comes back intact ---
RE_ROOT="$SANDBOX" RE_FORCE_RESTORE=1 \
  "$HERE/backup_artifacts.sh" restore "$archive" >/dev/null ||
  fail "forced restore exited nonzero"
(
  cd "$SANDBOX"
  sha256sum --quiet -c before.sha256
) || fail "restored bytes differ from the backed-up originals"
aside="$(find "$SANDBOX" -maxdepth 1 -type d -name 'worlds.pre-restore-*' | head -n1)"
[[ -n "$aside" ]] || fail "forced restore deleted the previous tree instead of moving it aside"
[[ -f "$aside/DrillWorld/operator-junk.bin" ]] ||
  fail "moved-aside tree lost its contents"
echo "drill: forced restore byte-identical, previous tree preserved aside"

# --- corrupt archive must be refused, not half-restored ---
cp "$archive" "$SANDBOX/backups/corrupt.tar.gz"
dd if=/dev/urandom of="$SANDBOX/backups/corrupt.tar.gz" bs=1 seek=200 \
  count=64 conv=notrunc status=none
rm -rf "$SANDBOX/worlds"
if RE_ROOT="$SANDBOX" \
  "$HERE/backup_artifacts.sh" restore "$SANDBOX/backups/corrupt.tar.gz" >/dev/null 2>&1; then
  fail "corrupt archive was accepted for restore"
fi
[[ ! -e "$SANDBOX/worlds" ]] ||
  fail "failed restore left a partial extraction behind"
echo "drill: corrupt archive refused, nothing extracted"

# --- installing a world must not delete the one already in GeneratedWorlds ---
# shellcheck source=scripts/generated-world.sh
source "$HERE/generated-world.sh"
GW="$SANDBOX/GeneratedWorlds"
mkdir -p "$GW/RealEarth" "$SANDBOX/worlds/DrillWorld"
head -c 256 /dev/urandom >"$GW/RealEarth/hand-tuned.bin"
head -c 65536 /dev/urandom >"$SANDBOX/worlds/DrillWorld/dtm.raw"
(
  cd "$GW/RealEarth"
  find . -type f -print0 | sort -z | xargs -0 sha256sum
) >"$SANDBOX/before-install.sha256"
install_generated_world "$SANDBOX/worlds/DrillWorld" "$GW" RealEarth >/dev/null ||
  fail "install_generated_world exited nonzero"
[[ -f "$GW/RealEarth/dtm.raw" ]] || fail "install did not place the baked world"
kept="$(find "$SANDBOX/GeneratedWorlds_trash" -maxdepth 1 -name '*__RealEarth' | head -n1)"
[[ -n "$kept" ]] || fail "previous GeneratedWorlds entry was not kept aside"
(
  cd "$kept"
  sha256sum --quiet -c "$SANDBOX/before-install.sha256"
) || fail "moved-aside world lost its contents"
# A second install inside the same second must not nest one world in another.
install_generated_world "$SANDBOX/worlds/DrillWorld" "$GW" RealEarth >/dev/null ||
  fail "repeat install exited nonzero"
[[ "$(find "$SANDBOX/GeneratedWorlds_trash" -maxdepth 1 -name '*__RealEarth*' | wc -l)" -eq 2 ]] ||
  fail "repeat install reused a trash name and nested the previous world"
echo "drill: world install keeps the previous tree aside"

# --- out-of-tree state: saves, installed worlds, install trash -------------
# The only irreplaceable state on a dedicated server lives outside the repo,
# and the artifact set is repo-relative. Prove the extra-path path end to end.
SAVES="$SANDBOX/userdata/Saves"
mkdir -p "$SAVES/MyWorld"
head -c 4096 /dev/urandom >"$SAVES/MyWorld/world.tdb"
printf 'level-data' >"$SAVES/MyWorld/player.tdb"
(
  cd "$SAVES"
  find . -type f -print0 | sort -z | xargs -0 sha256sum
) >"$SANDBOX/before-saves.sha256"

if ! RE_ROOT="$SANDBOX" RE_TERRARIUM_CACHE='' \
  RE_BACKUP_EXTRA_PATHS="saves=$SAVES" \
  "$HERE/backup_artifacts.sh" backup >/dev/null; then
  fail "backup with an extra path exited nonzero"
fi
extra_archive="$(find "$SANDBOX/backups" -name 'realearth-artifacts-*.tar.gz' -printf '%T@ %p\n' |
  sort -rn | head -n1 | cut -d' ' -f2-)"
tar -tzf "$extra_archive" | grep -q "^realearth-extra/saves/data/MyWorld/world.tdb$" ||
  fail "archive does not contain the out-of-tree save tree"
tar -xzOf "$extra_archive" realearth-extra/saves/.realearth-target |
  grep -qx "$SAVES" || fail "extra tree does not record its absolute target"
echo "drill: out-of-tree tree archived with its target path recorded"

# A typo'd or stale path must fail the backup, not silently drop the saves.
if RE_ROOT="$SANDBOX" RE_TERRARIUM_CACHE='' \
  RE_BACKUP_EXTRA_PATHS="saves=$SAVES/gone" \
  "$HERE/backup_artifacts.sh" backup >/dev/null 2>&1; then
  fail "backup accepted a nonexistent extra path"
fi
echo "drill: nonexistent extra path fails the backup"

# Restore must refuse to clobber a live save directory, then move it aside.
if ! RE_ROOT="$SANDBOX" RE_FORCE_RESTORE=1 \
  "$HERE/backup_artifacts.sh" restore "$extra_archive" >/dev/null 2>&1; then
  fail "forced restore exited nonzero on the extra tree"
fi
[[ -f "$SAVES/MyWorld/world.tdb" ]] || fail "forced restore lost the live save tree"
(cd "$SAVES" && sha256sum --quiet -c "$SANDBOX/before-saves.sha256") ||
  fail "restored save tree differs from the backed-up original"
kept_save="$(find "$SANDBOX/userdata" -maxdepth 1 -type d -name 'Saves.pre-restore-*' |
  head -n1)"
[[ -n "$kept_save" ]] ||
  fail "forced restore deleted the previous save tree instead of moving it aside"
[[ -f "$kept_save/MyWorld/world.tdb" ]] ||
  fail "moved-aside save tree lost its contents"

# Destroy it outright: a plain restore must put the saves back.
rm -rf "$SAVES" "$kept_save" "$SANDBOX/userdata"
RE_ROOT="$SANDBOX" "$HERE/backup_artifacts.sh" restore "$extra_archive" >/dev/null ||
  fail "restore of the out-of-tree tree exited nonzero"
[[ ! -e "$SANDBOX/realearth-extra" ]] ||
  fail "restore left the staging prefix behind in the repo root"
(cd "$SAVES" && sha256sum --quiet -c "$SANDBOX/before-saves.sha256") ||
  fail "save tree restored from the archive differs from the original"
echo "drill: out-of-tree tree round-trips through destroy and restore"

# --- retention: a bounded archive set, pruned only after a verified backup --
for _ in 1 2 3; do
  RE_ROOT="$SANDBOX" RE_TERRARIUM_CACHE='' RE_BACKUP_KEEP=2 \
    "$HERE/backup_artifacts.sh" backup >/dev/null ||
    fail "retention backup exited nonzero"
done
kept_count="$(find "$SANDBOX/backups" -name 'realearth-artifacts-*.tar.gz' | wc -l)"
[[ "$kept_count" -eq 2 ]] ||
  fail "RE_BACKUP_KEEP=2 left $kept_count archives"
RE_ROOT="$SANDBOX" RE_TERRARIUM_CACHE='' "$HERE/backup_artifacts.sh" status >/dev/null ||
  fail "status failed after pruning"
echo "drill: retention keeps the newest archives and leaves a fresh one"

echo "DRILL OK: backup -> destroy -> restore roundtrip proven"
