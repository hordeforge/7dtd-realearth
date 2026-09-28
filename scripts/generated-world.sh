# shellcheck shell=bash
# Sourced helper: install a baked world into a GeneratedWorlds target without
# ever deleting the tree already there.
#
# The previous world is renamed to GeneratedWorlds_trash/<UTC stamp>__<name>
# instead of being rm -rf'd, matching the save-trash window in
# scripts/run_dedicated_height_test.sh (RE_SAVE_TRASH_DAYS) and the bake
# guardrail in tools/realearth/bake_world.py:65. A GeneratedWorlds entry can carry
# hand-edited or differently generated state that no archive in backups/
# holds, so an install that overwrites it in place is an unrecoverable delete.
# The aside copy lives outside GeneratedWorlds so the game does not offer it
# as a selectable world; delete it once you are happy with the new world.
#
# Repeating the install is a fixed point: when the live world already is the
# source world, nothing is copied and nothing is moved aside. A world dir is
# not cheap (dtm.raw alone is hundreds of MB) and every install script calls
# this for each target, so a rerun used to fill the disk with trash copies of
# a world nobody replaced.
#
# Usage (after `source`ing):
#   install_generated_world "$ROOT/worlds/RealEarth" "$gw" RealEarth

# Days a moved-aside world stays recoverable. The trash is a guard against one
# bad install, not an archive (scripts/backup_artifacts.sh is that), so the
# window is bounded: without it a daily install of a large world grows the
# trash forever. 0 prunes on the next run.
WORLD_TRASH_DAYS="${RE_WORLD_TRASH_DAYS:-14}"

# A non-numeric window makes the prune's find fail, and the prune swallows that
# error, so the trash would grow without bound while every run reported success.
validate_world_trash_days() {
  case "$WORLD_TRASH_DAYS" in
    ""|*[!0-9]*)
      echo "ERROR: RE_WORLD_TRASH_DAYS must be a non-negative integer (got: $WORLD_TRASH_DAYS)" >&2
      return 2
      ;;
  esac
  return 0
}

# Sorted "<path>\t<size>\t<mtime>" listing of everything under $1. cp -a
# preserves size and mtime, so two trees with equal listings hold the same
# bytes from the same source; a game that touched the installed world changed
# its listing and the next install replaces it as before.
tree_signature() {
  ( cd "$1" && find . -mindepth 1 -printf '%P\t%s\t%T@\n' | LC_ALL=C sort )
}

# True when $2 is already a copy of $1. Any unreadable tree compares as
# different, so a failed listing falls back to a plain install.
world_is_current() {
  local src="$1" dest="$2" a b
  [[ -d "$dest" ]] || return 1
  a="$(tree_signature "$src" 2>/dev/null)" || return 1
  b="$(tree_signature "$dest" 2>/dev/null)" || return 1
  [[ -n "$a" && "$a" == "$b" ]]
}

# Move $2 out of the GeneratedWorlds dir $1 into a sibling trash dir. No-op
# when that world is not installed.
move_aside() {
  local gw="$1" name="$2" trash stamp dest
  [[ -e "${gw:?}/$name" ]] || return 0
  validate_world_trash_days
  trash="$(dirname "$gw")/$(basename "$gw")_trash"
  mkdir -p "$trash"
  # UTC stamp: a fall-back DST hour would repeat a local stamp and mv would
  # nest this entry inside the earlier one.
  stamp="$(date -u +%Y-%m-%d__%H-%M-%S)"
  dest="$trash/${stamp}__${name}"
  local n=1
  while [[ -e "$dest" ]]; do
    dest="$trash/${stamp}__${name}.${n}"
    n=$((n + 1))
  done
  mv "$gw/$name" "$dest"
  # mv keeps the old world dir's mtime, which the prune below reads as its age:
  # a bake from last month would be deleted the moment it is moved aside.
  touch "$dest"
  # Retention prune: the only deletion this helper performs, and only of
  # entries it put in the trash itself, past the window above.
  # shellcheck disable=SC2086 # the quoted window is validated to digits above
  find "$trash" -mindepth 1 -maxdepth 1 -name "*__${name}*" \
    -mtime "+$WORLD_TRASH_DAYS" -exec rm -rf -- {} + 2>/dev/null || true
  echo "Previous world kept at: $dest"
}

# Copy the baked world at $1 into the GeneratedWorlds directory $2 as $3.
install_generated_world() {
  local src="$1" gw="$2" name="$3"
  [[ -d "$src" ]] || return 0
  validate_world_trash_days
  mkdir -p "$gw"
  if world_is_current "$src" "$gw/$name"; then
    echo "World → $gw/$name (already installed, unchanged)"
    return 0
  fi
  move_aside "$gw" "$name"
  cp -a "$src" "$gw/$name"
  echo "World → $gw/$name"
}
