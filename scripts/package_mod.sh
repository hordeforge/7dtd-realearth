#!/usr/bin/env bash
# Assemble a Mods/RealEarth folder ready to copy into the game.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/dist/RealEarth}"
GAME_DIR="${SEVENDTD_GAME_DIR:-${GameDir:-}}"
# docs/MODLET.md: install/package scripts reject MAP_MODE values other than
# Streamed|Baked; the chosen mode is baked into the packaged config.
MAP_MODE="${MAP_MODE:-Streamed}"
# Streamer window the client keeps resident; mirrors realearth.DEFAULT_LOCAL_WINDOW_SIZE.
LOCAL_WINDOW_SIZE=1024
case "$MAP_MODE" in
  Streamed|Baked) ;;
  *)
    echo "ERROR: MAP_MODE must be Streamed or Baked (got: $MAP_MODE)" >&2
    exit 1
    ;;
esac

# The shipped Config/realearth.json is generated through realearth.mod_config
# (MAP_MODE + product defaults below); skipping it would silently package
# template defaults that ignore them, so python3 is a hard requirement.
if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 is required to write the packaged config" >&2
  exit 1
fi
# The positional is rm -rf'd below: refuse anything that is not a safe
# destination name/path (empty, root, or a traversal escape).
case "$OUT" in
  ""|/|*..*)
    echo "ERROR: package output path must be a plain directory (got: '$OUT')" >&2
    exit 1
    ;;
esac

# Locate a .NET SDK: explicit env, then the usual local caches (mirrors Makefile
# and install_proton.sh; a bare dotnet host without SDKs fails cryptically).
find_dotnet_root() {
  for d in "${DOTNET_ROOT:-}" "$HOME/.cache/dotnet-sdk" "$HOME/.dotnet" \
           "/usr/lib/dotnet" "/usr/share/dotnet" "/usr/local/share/dotnet"; do
    if [[ -n "$d" && -x "$d/dotnet" ]]; then
      echo "$d"
      return 0
    fi
  done
  echo ""
}
if [[ -z "${DOTNET_ROOT:-}" ]]; then
  DOTNET_ROOT="$(find_dotnet_root)"
fi
export PATH="${DOTNET_ROOT:+$DOTNET_ROOT:}${PATH}"

rm -rf "$OUT"
mkdir -p "$OUT/Config" "$OUT/Data" "$OUT"

cp "$ROOT/ModInfo.xml" "$OUT/"
cp "$ROOT/Config/realearth.json" "$OUT/Config/"
[[ -f "$ROOT/Config/nav_objects.xml" ]] && cp -f "$ROOT/Config/nav_objects.xml" "$OUT/Config/"
cp "$ROOT/ATTRIBUTION.md" "$OUT/" 2>/dev/null || true
cp "$ROOT/CHANGELOG.md" "$OUT/" 2>/dev/null || true
# Ensure single-world defaults are present in packaged config
# Real-height product default (docs/HEIGHT_LIMITS.md): expand required, no
# compression. Debug FOW keys stay OFF in shipped packages (dev values:
# reveal=true, radius=128).
PYTHONPATH="$ROOT/tools" python3 -m realearth.mod_config write "$OUT" "$ROOT" \
  --template "$ROOT/Config/realearth.json" \
  "MapMode=$MAP_MODE" \
  EngineHeightStockSafe=false \
  "SingleWorldSession?=true" \
  "LocalWindowSize?=$LOCAL_WINDOW_SIZE" \
  "MultiplayerOriginMode?=SoloSlide" \
  "StreamRadiusTiles?=2" \
  "UnloadRadiusTiles?=4" \
  "DebugRevealFullMap?=false" \
  "ShowCityNamesOnMap?=true" \
  "CityMapDiscoverRadiusScale?=1.0" \
  "DebugMapRevealRadiusChunks?=0" \
  "EnableEngineHeightMod?=true"
if [[ -f "$ROOT/Config/realearth.advanced_height.json" ]]; then
  cp "$ROOT/Config/realearth.advanced_height.json" "$OUT/Config/"
fi
# Multiplayer SharedFixed template (copy over realearth.json on dedicated)
if [[ -f "$ROOT/Config/realearth.mp.json" ]]; then
  cp "$ROOT/Config/realearth.mp.json" "$OUT/Config/"
fi
if [[ -f "$ROOT/docs/MODLET.md" ]]; then
  mkdir -p "$OUT/Docs"
  cp "$ROOT/docs/MODLET.md" "$OUT/Docs/INSTALL.md"
  cp "$ROOT/docs/MODLET.md" "$OUT/Docs/MODLET.md"
fi
if [[ -f "$ROOT/docs/HEIGHT_LIMITS.md" ]]; then
  mkdir -p "$OUT/Docs"
  cp "$ROOT/docs/HEIGHT_LIMITS.md" "$OUT/Docs/"
fi
if [[ -f "$ROOT/docs/CITY_MAP_LABELS.md" ]]; then
  mkdir -p "$OUT/Docs"
  cp "$ROOT/docs/CITY_MAP_LABELS.md" "$OUT/Docs/"
fi
if [[ -f "$ROOT/docs/LON_LAT.md" ]]; then
  mkdir -p "$OUT/Docs"
  cp "$ROOT/docs/LON_LAT.md" "$OUT/Docs/"
fi
if [[ -f "$ROOT/docs/GAP_HARMONY_MODLETS.md" ]]; then
  mkdir -p "$OUT/Docs"
  cp "$ROOT/docs/GAP_HARMONY_MODLETS.md" "$OUT/Docs/"
fi
if [[ -f "$ROOT/docs/INDEX.md" ]]; then
  mkdir -p "$OUT/Docs"
  cp "$ROOT/docs/INDEX.md" "$OUT/Docs/"
fi
if [[ -f "$ROOT/docs/MULTIPLAYER_STREAMING.md" ]]; then
  mkdir -p "$OUT/Docs"
  cp "$ROOT/docs/MULTIPLAYER_STREAMING.md" "$OUT/Docs/"
fi

if [[ -d "$ROOT/data/samples/demo_region" ]]; then
  mkdir -p "$OUT/Data/tiles"
  cp -a "$ROOT/data/samples/demo_region/." "$OUT/Data/tiles/"
  # Point config at the packaged tiles and take the canvas from their manifest:
  # the demo pack is a local-indexed region, far below a planet canvas, so it
  # must not wrap at the antimeridian.
  PYTHONPATH="$ROOT/tools" python3 -m realearth.mod_config write "$OUT" "$ROOT" \
    --template "$OUT/Config/realearth.json" \
    --sync-manifest --max-window "$LOCAL_WINDOW_SIZE" \
    TilePackPath=Data/tiles
else
  echo "NOTE: no pack at data/samples/demo_region, run make demo; shipping without Data/tiles." >&2
fi

if [[ -n "$GAME_DIR" && -d "$GAME_DIR" ]]; then
  echo "Building C# against $GAME_DIR ..."
  dotnet build "$ROOT/Source/RealEarth/RealEarth.csproj" -c Release -p:GameDir="$GAME_DIR"
  DLL="$ROOT/Source/RealEarth/bin/Release/RealEarth.dll"
  if [[ ! -f "$DLL" ]]; then
    DLL="$ROOT/Source/RealEarth/bin/Release/net48/RealEarth.dll"
  fi
  if [[ -f "$DLL" ]]; then
    cp "$DLL" "$OUT/"
  else
    # A package without the mod DLL is not a successful build: the game would
    # load an empty mod folder. Fail loudly instead of shipping it.
    echo "ERROR: dotnet build succeeded but no RealEarth.dll found under Source/RealEarth/bin/" >&2
    exit 1
  fi
else
  echo "NOTE: set SEVENDTD_GAME_DIR to build RealEarth.dll into the package."
  echo "      Heightmap export under Data/tiles/export_7dtd still works without the DLL."
fi

# Stock dashboard webui (WebMod auto-served by the game webserver). Build
# output lives in webmod/build (see build-webmod.sh for why); the packaged
# folder keeps the game-required WebMod name.
if [[ -d "$ROOT/webmod/build" ]]; then
  mkdir -p "$OUT/WebMod"
  cp -a "$ROOT/webmod/build/." "$OUT/WebMod/"
  # bundle.js.map is a devtools aid for debugging the minified bundle; the
  # shipped dashboard needs only bundle.js + styling.css.
  rm -f "$OUT/WebMod/bundle.js.map"
  echo "Packaged WebMod/ (stock dashboard webui)"
else
  echo "NOTE: no webmod/build output, run make webmod-export + make webmod to include the dashboard webui."
fi

# RealEarth YDim expand tools (part of this mod)
mkdir -p "$OUT/Tools"
PATCHER_SRC="$ROOT/tools/engine_patcher/bin/Release"
if [[ ! -f "$PATCHER_SRC/EngineHeightPatcher.exe" && -n "${GAME_DIR:-}" ]]; then
  HARMONY="${GAME_DIR}/Mods/0_TFP_Harmony"
  if [[ -d "$HARMONY" ]] && command -v dotnet >/dev/null; then
    echo "Building RealEarth EngineHeightPatcher into package..."
    dotnet build "$ROOT/tools/engine_patcher/EngineHeightPatcher.csproj" -c Release \
      -p:HarmonyDir="$HARMONY" -v q
  fi
fi
if [[ -f "$PATCHER_SRC/EngineHeightPatcher.exe" ]]; then
  cp -f "$PATCHER_SRC/EngineHeightPatcher.exe" "$OUT/Tools/"
  [[ -f "$PATCHER_SRC/Mono.Cecil.dll" ]] && cp -f "$PATCHER_SRC/Mono.Cecil.dll" "$OUT/Tools/"
  if [[ -f "$ROOT/scripts/apply_engine_expand.sh" ]]; then
    cp -f "$ROOT/scripts/apply_engine_expand.sh" "$OUT/Tools/"
    chmod +x "$OUT/Tools/apply_engine_expand.sh"
  fi
  cat > "$OUT/Tools/README.txt" <<'EOF'
RealEarth YDim expand (part of this mod)
----------------------------------------
Raises 7DTD Assembly-CSharp vertical limits for 1:1 RealEarth heights.

  1. Close 7 Days to Die completely.
  2. Run:  ./apply_engine_expand.sh
     or:   mono EngineHeightPatcher.exe --dll "/path/to/Assembly-CSharp.dll" --force
  3. Restart the game. Log should show: ENGINE EXPANDED / YDim=16384

Backup: Assembly-CSharp.dll.re_stock_bak next to the game DLL.
Restore: make engine-restore from the RealEarth repo, or Steam Verify.
EOF
  echo "Packaged RealEarth Tools/ (YDim expand)"
else
  echo "NOTE: EngineHeightPatcher not built, run make engine-expand from the repo after install."
fi

echo "Packaged → $OUT"
echo "Copy into: <7DaysToDie>/Mods/RealEarth/"
echo "Full RealEarth: run Tools/apply_engine_expand.sh (YDim expand is part of this mod)."
echo "See Docs/MODLET.md"