#!/usr/bin/env bash
# RealEarth YDim expand (part of this mod). Builds EngineHeightPatcher then applies.
# Prefer: make engine-expand  |  Mods/RealEarth/Tools/apply_engine_expand.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GAME_DIR="${SEVENDTD_GAME_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days To Die}"
HARMONY="$GAME_DIR/Mods/0_TFP_Harmony"
PATCHER_PROJ="$ROOT/tools/engine_patcher/EngineHeightPatcher.csproj"
export DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.cache/dotnet-sdk}"
export PATH="${DOTNET_ROOT}:${PATH}"

if [[ ! -f "$GAME_DIR/7DaysToDie_Data/Managed/Assembly-CSharp.dll" ]]; then
  echo "ERROR: game DLL not found under $GAME_DIR" >&2
  exit 2
fi
if [[ ! -d "$HARMONY" ]]; then
  echo "ERROR: 0_TFP_Harmony not found: $HARMONY" >&2
  exit 2
fi
if ! command -v dotnet >/dev/null; then
  echo "ERROR: dotnet SDK required to build EngineHeightPatcher" >&2
  exit 2
fi

echo "=== RealEarth: build EngineHeightPatcher ==="
dotnet build "$PATCHER_PROJ" -c Release -p:HarmonyDir="$HARMONY" -v q

chmod +x "$ROOT/scripts/apply_engine_expand.sh"
# Default --force so re-runs from stock backup stay consistent
exec "$ROOT/scripts/apply_engine_expand.sh" --force "$@"
