#!/usr/bin/env bash
# Headless-browser smoke test for the viewer (requires chromium + the local
# viewer server). Exercises the BUILT modules (js/pack.js, js/rte.js,
# js/rteLayer.js) through a real browser engine: pack parsing + schema
# validation, .rte decoding, relief canvas render, and synthetic
# keyboard/pointer/touch dispatch. Every check must print PASS.
#
# Usage: bash scripts/test-viewer-smoke.sh
# (starts its own server on port 8765 unless RE_VIEWER_SMOKE_PORT is set)

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${RE_VIEWER_SMOKE_PORT:-8765}"
case "$PORT" in
  ""|*[!0-9]*)
    # Port lands in curl URLs and the server --port flag; a non-numeric value
    # would surface as a curl URL error instead of naming the bad variable.
    echo "ERROR: RE_VIEWER_SMOKE_PORT must be a positive integer (got: $PORT)" >&2
    exit 2
    ;;
esac
# Scratch lives under the repo's git-ignored .scratch/, not TMPDIR: /tmp is
# tmpfs on most Linux hosts, and a fixed /tmp log path collides with any other
# run of this script on the same host.
SCRATCH="${RE_SCRATCH:-$ROOT/.scratch}"
mkdir -p "$SCRATCH"
SERVER_LOG="$SCRATCH/re_viewer_smoke.log"
OUT="$SCRATCH/re_viewer_smoke.dom"
CHROMIUM="$(command -v chromium || command -v chromium-browser || true)"
if [[ -z "$CHROMIUM" ]]; then
  echo "SKIP: chromium not installed" >&2
  exit 0
fi

# Serve the viewer if nothing is listening yet.
if ! curl -s -o /dev/null "http://127.0.0.1:${PORT}/index.html"; then
  (cd "$ROOT" && PYTHONPATH="$ROOT/tools" python3 -m realearth.cli serve \
    --port "$PORT" --no-browser >"$SERVER_LOG" 2>&1) &
  SERVER_PID=$!
  trap 'kill $SERVER_PID 2>/dev/null || true; rm -f "$OUT"' EXIT
  for _ in $(seq 1 20); do
    curl -s -o /dev/null "http://127.0.0.1:${PORT}/index.html" && break
    sleep 0.5
  done
fi

# A missing harness page is a missing prerequisite, not a smoke failure: the
# browser would dump a 404 body and every check would report FAIL for a reason
# that has nothing to do with the viewer.
HARNESS="${RE_VIEWER_SMOKE_HARNESS:-$ROOT/viewer/data/smoke.html}"
if ! curl -s -o /dev/null -f "http://127.0.0.1:${PORT}/data/smoke.html"; then
  echo "realearth: viewer smoke cannot run, harness page not served at /data/smoke.html" >&2
  echo "  expected: $HARNESS (export the demo pack: make viewer)" >&2
  exit 1
fi

timeout 60 "$CHROMIUM" --headless --no-sandbox --disable-gpu \
  --virtual-time-budget=15000 --run-all-compositor-stages-before-draw \
  --dump-dom "http://127.0.0.1:${PORT}/data/smoke.html" 2>/dev/null >"$OUT" || true

# The harness writes one PASS/FAIL line per check into <pre id="out">.
RESULTS="$(sed -n '/<pre id="out">/,$p' "$OUT" |
  sed -e 's|.*<pre id="out">||' -e 's|</pre>.*||')"
[[ -n "$RESULTS" ]] || RESULTS="FAIL harness produced no output"
echo "$RESULTS"
rm -f "$OUT"
FAILS="$(echo "$RESULTS" | grep -cE "^FAIL" || true)"
if [[ "$FAILS" -ne 0 ]]; then
  echo "realearth: viewer smoke FAILED ($FAILS), server log: $SERVER_LOG" >&2
  exit 1
fi
echo "realearth: viewer smoke ok"
