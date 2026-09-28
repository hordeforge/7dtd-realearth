#!/usr/bin/env bash
# Set a key in the [General] section of a 7DTD UserOptions.ini.
#
# Appending the key every run was the old behaviour: a dedicated launcher that
# is restarted appends a second copy, then a third, and the file grows without
# bound while the effective value depends on how many times the script ran.
# This rewrite is a fixed point instead: every existing copy of the key is
# dropped (any case, any indentation, any section) and exactly one is written
# under [General], so running it twice leaves the file byte-identical to
# running it once. Other keys, sections and comments are preserved in order,
# and the file's own line ending is kept, so rewriting the CRLF ini the
# Windows game writes does not hand it back a half-LF file.
#
# Usage:
#   scripts/useroptions_ini.sh FILE KEY=VALUE
#   source scripts/useroptions_ini.sh; re_set_ini_general_value FILE KEY=VALUE
set -euo pipefail

usage() {
  # Header comment with the leading '# ' stripped; a fixed line range would
  # shift whenever a note is added above it.
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

re_set_ini_general_value() {
  local file="$1" pair key value scratch crlf
  pair="${2:?usage: re_set_ini_general_value FILE KEY=VALUE}"
  key="${pair%%=*}"
  value="${pair#*=}"
  if [[ -z "$key" || "$pair" != *=* ]]; then
    echo "ERROR: assignment must be KEY=VALUE, got: $pair" >&2
    return 2
  fi
  mkdir -p "$(dirname "$file")"
  [[ -f "$file" ]] || : >"$file"
  # Scratch sits next to the target (same filesystem, never tmpfs) and is
  # removed on every exit path, so a crashed run leaves no residue.
  scratch="$file.re-set.$$"
  trap 'rm -f "$scratch"' RETURN
  # The game writes this ini itself and uses CRLF on its Windows build (the
  # Proton client and the Windows dedicated), LF on the native Linux one. awk
  # always emits LF, so a plain rewrite would leave the game's CRLF file half
  # converted. Detect the file's own ending and write every line, kept and new,
  # with it.
  crlf=0
  if [[ -s "$file" ]] && LC_ALL=C grep -q $'\r$' "$file"; then crlf=1; fi
  awk -v want="$key" -v line="$key=$value" -v crlf="$crlf" '
    BEGIN { ORS = crlf ? "\r\n" : "\n" }
    {
      # Drop the record carriage return so kept lines do not gain a second one
      # once ORS carries it.
      rec = $0
      sub(/\r$/, "", rec)
      probe = rec
      gsub(/^[ \t]+/, "", probe)
      gsub(/[ \t]+$/, "", probe)
      # "DiscordDisabled = false" and "  discorddisabled=x" are the same key.
      bare = probe
      gsub(/[ \t]/, "", bare)
      if (index(tolower(bare), tolower(want) "=") == 1) next
      if (!inserted && tolower(bare) == "[general]") {
        print rec
        print line
        inserted = 1
        next
      }
      print rec
    }
    END {
      if (!inserted) {
        if (NR > 0) print ""
        print "[General]"
        print line
      }
    }
  ' "$file" >"$scratch"
  # cat > keeps the inode and permissions the game wrote the file with.
  cat "$scratch" >"$file"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  re_set_ini_general_value "$@"
fi
