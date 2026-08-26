#!/usr/bin/env bash
# RealEarth YDim expand (part of this mod). Builds EngineHeightPatcher then applies.
# Prefer: make engine-expand  |  Mods/RealEarth/Tools/apply_engine_expand.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GAME_DIR="${SEVENDTD_GAME_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days To Die}"
HARMONY="$GAME_DIR/Mods/0_TFP_Harmony"
PATCHER_PROJ="$ROOT/tools/engine_patcher/EngineHeightPatcher.csproj"
# Locate a .NET SDK: explicit env first, then the usual local caches (mirrors
# Makefile and install_proton.sh). Never export a DOTNET_ROOT without a dotnet
# binary: apphosts resolve libhostfxr through it and fail to launch otherwise.
for d in "${DOTNET_ROOT:-}" "$HOME/.cache/dotnet-sdk" "$HOME/.dotnet" \
         "/usr/lib/dotnet" "/usr/share/dotnet" "/usr/local/share/dotnet"; do
  if [[ -n "$d" && -x "$d/dotnet" ]]; then
    export DOTNET_ROOT="$d"
    break
  fi
done
export PATH="${DOTNET_ROOT:+$DOTNET_ROOT:}${PATH}"

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
