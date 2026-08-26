#!/usr/bin/env bash
# Prove the artifact backup/restore roundtrip instead of trusting job exit
# codes. Builds a sandbox tree shaped like real state (worlds/, tile pack,
# terrarium cache, viewer exports), backs it up via backup_artifacts.sh,
# destroys the artifacts, restores them, and compares every file byte-for-
# byte. Also asserts the guardrails hold when it matters: an existing tree
# is never clobbered without RE_FORCE_RESTORE=1, a forced restore moves the
# old tree aside instead of deleting it, and a corrupt archive is refused.
#
# Runs entirely inside a mktemp sandbox (RE_ROOT override) and removes it
# on exit; the repo and any real artifacts are never touched.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/realearth-drill.XXXXXX")"
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
RE_ROOT="$SANDBOX" "$HERE/backup_artifacts.sh" backup >/dev/null ||
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

echo "DRILL OK: backup -> destroy -> restore roundtrip proven"
