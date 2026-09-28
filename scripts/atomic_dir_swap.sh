#!/usr/bin/env bash
# Publish a freshly built directory over a live one without ever leaving the
# live path absent or half-written. Sourced by the install scripts; not run.
#
#   atomic_swap_begin   DEST   create a sibling staging dir, register it for cleanup
#   atomic_swap_publish DEST   move DEST aside, rename staging onto it, drop the aside copy
#
# Staging is a sibling of DEST so both renames stay on one filesystem. If the
# copy that fills the staging dir fails, the script exits, the EXIT trap calls
# atomic_swap_cleanup, and the previous install is left exactly as it was: a
# Mods/RealEarth or GeneratedWorlds/RealEarth the game can still load.

RE_ATOMIC_STAGING=""

atomic_swap_cleanup() {
  if [[ -n "$RE_ATOMIC_STAGING" && -d "$RE_ATOMIC_STAGING" ]]; then
    rm -rf "$RE_ATOMIC_STAGING"
  fi
  return 0
}

atomic_swap_begin() {
  local dest="$1"
  local parent base
  parent="$(dirname "$dest")"
  base="$(basename "$dest")"
  RE_ATOMIC_STAGING="$parent/.$base.staging.$$"
  rm -rf "$RE_ATOMIC_STAGING"
  mkdir -p "$RE_ATOMIC_STAGING"
}

atomic_swap_publish() {
  local dest="$1"
  local stage="$RE_ATOMIC_STAGING"
  local previous="$dest.previous.$$"
  if [[ -z "$stage" || ! -d "$stage" ]]; then
    echo "ERROR: no staging directory for $dest; call atomic_swap_begin first" >&2
    return 1
  fi
  rm -rf "$previous"
  if [[ -e "$dest" ]]; then
    mv "$dest" "$previous"
  fi
  mv "$stage" "$dest"
  rm -rf "$previous"
  RE_ATOMIC_STAGING=""
}
