# shellcheck shell=bash
# Sourced helper: install a baked world into a GeneratedWorlds target without
# ever deleting the tree already there.
#
# The previous world is renamed to GeneratedWorlds_trash/<UTC stamp>__<name>
# instead of being rm -rf'd, matching the save-trash window in
# scripts/run_dedicated_height_test.sh:170 and the bake guardrail in
# tools/realearth/bake_world.py:65. A GeneratedWorlds entry can carry
# hand-edited or differently generated state that no archive in backups/
# holds, so an install that overwrites it in place is an unrecoverable delete.
# The aside copy lives outside GeneratedWorlds so the game does not offer it
# as a selectable world; delete it once you are happy with the new world.
#
# Usage (after `source`ing):
#   install_generated_world "$ROOT/worlds/RealEarth" "$gw" RealEarth

# Move $2 out of the GeneratedWorlds dir $1 into a sibling trash dir. No-op
# when that world is not installed.
move_aside() {
  local gw="$1" name="$2" trash stamp dest
  [[ -e "${gw:?}/$name" ]] || return 0
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
  echo "Previous world kept at: $dest"
}

# Copy the baked world at $1 into the GeneratedWorlds directory $2 as $3.
install_generated_world() {
  local src="$1" gw="$2" name="$3"
  [[ -d "$src" ]] || return 0
  mkdir -p "$gw"
  move_aside "$gw" "$name"
  cp -a "$src" "$gw/$name"
  echo "World → $gw/$name"
}
