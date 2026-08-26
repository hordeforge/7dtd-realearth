#!/usr/bin/env bash
# Gate the shipped HTML and CSS through the W3C Nu Html Checker (vnu).
#
# vnu ships as a jar; vnu-jar wraps it and downloads a JRE on first install.
# Pinned by VNU_VERSION in scripts/toolchain-versions.env (single source of
# truth for every build/lint pin): the repo tracks no package.json.
# Override locally: VNU_VERSION=26.8.21 bash scripts/lint-html.sh
#
# Any vnu output fails the gate, not just errors: an "info" about a stray
# trailing slash or a warning about a redundant ARIA attribute is a real
# finding, and letting them accumulate is how the signal dies.
#
# Requires: bun (bunx), java.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$root/scripts/toolchain-versions.env"
# Install into the shared lint cache rather than running bunx from the repo:
# a bare bunx writes a lockfile beside the working directory.
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/realearth/oxlint-standards"

html_files=("$root/viewer/index.html")
css_files=("$root/viewer/css/app.css" "$root/webmod/styling.css")

mkdir -p "$cache_dir"
[ -f "$cache_dir/package.json" ] || printf '{"type":"module"}\n' > "$cache_dir/package.json"
( cd "$cache_dir" && bun add --silent "vnu-jar@$VNU_VERSION" ) >/dev/null 2>&1 || {
  echo "realearth: lint-html: could not install vnu-jar@$VNU_VERSION into $cache_dir (offline?)" >&2
  exit 1
}
vnu="$cache_dir/node_modules/.bin/vnu"

run_vnu() {
  local label="$1"
  shift
  local output
  # vnu exits non-zero on errors only, so capture and judge the text instead.
  if ! output="$("$vnu" "$@" 2>&1)"; then
    printf '%s\n' "$output" >&2
    echo "realearth: lint-html: vnu failed on $label" >&2
    return 1
  fi
  # The one expected line is the completion notice; anything else is a finding.
  if printf '%s\n' "$output" | grep -qvE '^(Document checking completed\. No errors found\.)?$'; then
    printf '%s\n' "$output" >&2
    echo "realearth: lint-html: $label must validate with zero findings" >&2
    return 1
  fi
}

run_vnu "HTML" --format text "${html_files[@]}"
run_vnu "CSS" --format text --css "${css_files[@]}"

echo "realearth: lint-html: vnu HTML and CSS validation ok"
