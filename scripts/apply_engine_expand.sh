#!/usr/bin/env bash
# RealEarth YDim expand (part of this mod).
# Patches 7DTD Assembly-CSharp for 1:1 vertical heights. Creates *.re_stock_bak.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$HERE/EngineHeightPatcher.exe" ]]; then
  TOOLS="$HERE"
  ROOT="$(cd "$HERE/../.." 2>/dev/null && pwd || echo "$HERE")"
else
  ROOT="$(cd "$HERE/.." && pwd)"
  TOOLS="$ROOT/tools/engine_patcher/bin/Release"
fi

GAME_DIR="${SEVENDTD_GAME_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days To Die}"
DS_DIR="${SEVENDTD_SERVER_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days to Die Dedicated Server}"
CLIENT_DLL="$GAME_DIR/7DaysToDie_Data/Managed/Assembly-CSharp.dll"
DS_DLL="$DS_DIR/7DaysToDieServer_Data/Managed/Assembly-CSharp.dll"
HARMONY="${HARMONY_DIR:-$GAME_DIR/Mods/0_TFP_Harmony}"
YDIM="${RE_YDIM:-16384}"

# Parse --ydim from args for display; pass all args through to patcher
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ydim) YDIM="$2"; EXTRA+=(--ydim "$2"); shift 2 ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

PATCHER="$TOOLS/EngineHeightPatcher.exe"
if [[ ! -f "$PATCHER" ]]; then
  echo "Building RealEarth EngineHeightPatcher..."
  export DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.cache/dotnet-sdk}"
  export PATH="${DOTNET_ROOT}:${PATH}"
  if [[ -f "$ROOT/tools/engine_patcher/EngineHeightPatcher.csproj" ]]; then
    dotnet build "$ROOT/tools/engine_patcher/EngineHeightPatcher.csproj" -c Release \
      -p:HarmonyDir="$HARMONY" -v q
    PATCHER="$ROOT/tools/engine_patcher/bin/Release/EngineHeightPatcher.exe"
    TOOLS="$(dirname "$PATCHER")"
  fi
fi
if [[ -f "$PATCHER" ]]; then
  :
else
  echo "ERROR: EngineHeightPatcher.exe not found" >&2
  exit 2
fi

if [[ ! -f "$TOOLS/Mono.Cecil.dll" && -f "$HARMONY/Mono.Cecil.dll" ]]; then
  cp -f "$HARMONY/Mono.Cecil.dll" "$TOOLS/" 2>/dev/null || true
fi

run_one() {
  local dll="$1"
  echo "=== RealEarth YDim expand → $dll (YDim=$YDIM) ==="
  if command -v mono >/dev/null; then
    mono "$PATCHER" --dll "$dll" --ydim "$YDIM" "${EXTRA[@]}"
  else
    "$PATCHER" --dll "$dll" --ydim "$YDIM" "${EXTRA[@]}"
  fi
}

if [[ ! -f "$CLIENT_DLL" ]]; then
  echo "ERROR: client DLL missing: $CLIENT_DLL" >&2
  exit 2
fi
run_one "$CLIENT_DLL"

if [[ -f "$DS_DLL" ]]; then
  run_one "$DS_DLL"
else
  echo "NOTE: dedicated server DLL not found (skip)"
fi

echo
echo "RealEarth YDim expand applied. Restart 7DTD."
echo "Log should show: ENGINE EXPANDED / YDim=$YDIM / heightMode=ydim-expanded"
echo "Restore: make engine-restore  (or Steam Verify)"
