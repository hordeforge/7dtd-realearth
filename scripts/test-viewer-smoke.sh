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
CHROMIUM="$(command -v chromium || command -v chromium-browser || true)"
if [[ -z "$CHROMIUM" ]]; then
  echo "SKIP: chromium not installed" >&2
  exit 0
fi

# Serve the viewer if nothing is listening yet.
if ! curl -s -o /dev/null "http://127.0.0.1:${PORT}/index.html"; then
  (cd "$ROOT" && PYTHONPATH="$ROOT/tools" python3 -m realearth.cli serve \
    --port "$PORT" --no-browser > /tmp/re_viewer_smoke.log 2>&1) &
  SERVER_PID=$!
  trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
  for _ in $(seq 1 20); do
    curl -s -o /dev/null "http://127.0.0.1:${PORT}/index.html" && break
    sleep 0.5
  done
fi

OUT="$(mktemp)"
timeout 60 "$CHROMIUM" --headless --no-sandbox --disable-gpu \
  --virtual-time-budget=15000 --run-all-compositor-stages-before-draw \
  --dump-dom "http://127.0.0.1:${PORT}/data/smoke.html" 2>/dev/null > "$OUT" || true

RESULTS="$(python3 - "$OUT" <<'PYEOF'
import re, sys
html = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'<pre id="out">(.*?)</pre>', html, re.S)
print(m.group(1) if m else "FAIL harness produced no output")
PYEOF
)"
echo "$RESULTS"
FAILS="$(echo "$RESULTS" | grep -cE "^FAIL" || true)"
if [[ "$FAILS" -ne 0 ]]; then
  echo "realearth: viewer smoke FAILED ($FAILS)" >&2
  exit 1
fi
echo "realearth: viewer smoke ok"
