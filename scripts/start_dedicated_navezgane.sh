#!/usr/bin/env bash
# Thin wrapper: stock Navezgane via start_dedicated_prefab.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export RE_WORLD_NAME="${RE_WORLD_NAME:-Navezgane}"
export RE_GAME_NAME="${RE_GAME_NAME:-BotPoiNavezgane}"
exec "$ROOT/scripts/start_dedicated_prefab.sh"
