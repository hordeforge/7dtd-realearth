#!/usr/bin/env bash
# Install the pinned JS build/lint toolchain (oxlint, tsc, vnu, three) into the
# shared cache directory, verified against the committed lockfile.
#
# The pins in scripts/toolchain-versions.env stay the single source of truth for
# versions; scripts/js-toolchain.lock records the exact artifacts those pins
# resolve to, with the sha512 bun verifies on install. The manifest below is
# generated from the pins, so a pin bumped without re-locking fails the install
# instead of silently pulling a different artifact.
#
# Usage: bash scripts/install-js-toolchain.sh CACHE_DIR
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$root/scripts/toolchain-versions.env"

case "${1:-}" in
  -h | --help)
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"
    exit 0
    ;;
esac
if [[ $# -lt 1 ]]; then
  echo "ERROR: install-js-toolchain.sh needs a CACHE_DIR" >&2
  exit 2
fi
cache_dir="$1"
mkdir -p "$cache_dir"

# type module: the vendored anti-slop plugin source is ESM, and without the
# field the runtime reparses it with a MODULE_TYPELESS_PACKAGE_JSON warning.
cat > "$cache_dir/package.json" <<JSON
{
  "type": "module",
  "dependencies": {
    "@oxlint/plugins": "$OXLINT_PLUGINS_VERSION",
    "@rikalabs/oxlint-standards": "$OXLINT_STANDARDS_VERSION",
    "@types/three": "$THREE_TYPES_VERSION",
    "oxlint-tsgolint": "$OXLINT_TSGOLINT_VERSION",
    "three": "$THREE_VERSION",
    "typescript": "$TSC_VERSION",
    "vnu-jar": "$VNU_VERSION"
  }
}
JSON

cp -f "$root/scripts/js-toolchain.lock" "$cache_dir/bun.lock"

# GitHub archive downloads fail intermittently; retry with deterministic
# backoff so a transient 5xx does not turn the lint stage red.
fetch_retry() {
  local url="$1" out="$2" attempt delay
  for attempt in 1 2 3; do
    if curl -fsSL "$url" -o "$out"; then
      return 0
    fi
    rm -f "$out"
    delay=$((attempt * 2))
    echo "realearth: install-js-toolchain: fetch failed (attempt $attempt), retrying in ${delay}s" >&2
    sleep "$delay"
  done
  return 1
}

# The @rikalabs rule set loads a vendored copy of dmmulroy/anti-slop (git
# commit, not an npm release), so the plugin source cannot come from the
# lockfile. It is pinned by commit and sha256 in toolchain-versions.env: a
# changed or truncated download fails here instead of feeding different plugin
# source into the lint gate.
if [ ! -d "$cache_dir/anti-slop-src" ]; then
  fetch_retry "https://github.com/dmmulroy/anti-slop/archive/$ANTI_SLOP_SHA.tar.gz" \
    "$cache_dir/anti-slop.tar.gz"
  if ! echo "${ANTI_SLOP_SHA256}  $cache_dir/anti-slop.tar.gz" | sha256sum -c - >/dev/null 2>&1; then
    rm -f "$cache_dir/anti-slop.tar.gz"
    echo "realearth: install-js-toolchain: anti-slop tarball sha256 mismatch (expected $ANTI_SLOP_SHA256)" >&2
    exit 1
  fi
  mkdir -p "$cache_dir/anti-slop-src"
  tar xzf "$cache_dir/anti-slop.tar.gz" -C "$cache_dir/anti-slop-src" --strip-components=2 "anti-slop-$ANTI_SLOP_SHA/src"
fi

# --frozen-lockfile: fail rather than re-resolve. A pin bumped without
# re-locking, or a lockfile that no longer matches the registry, stops the
# lint stage here.
( cd "$cache_dir" && bun install --frozen-lockfile ) >/dev/null 2>&1 || {
  echo "realearth: install-js-toolchain: bun install --frozen-lockfile failed in $cache_dir." >&2
  echo "realearth: a pin in scripts/toolchain-versions.env is not in scripts/js-toolchain.lock;" >&2
  echo "realearth: see the re-lock note at the top of that file." >&2
  exit 1
}

echo "OK js toolchain installed in $cache_dir (pinned + lockfile-verified)"
