#!/usr/bin/env bash
# Install RealEarth mod + GeneratedWorld into Steam/Proton Windows 7DTD.
# World data goes into the Proton Windows Roaming folder (NOT native ~/.local/share).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GAME_DIR="${SEVENDTD_GAME_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days To Die}"
DS_DIR="${SEVENDTD_SERVER_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days to Die Dedicated Server}"
# Locate a .NET SDK: explicit env, then the usual local caches (mirrors Makefile).
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

if [[ ! -d "$GAME_DIR/7DaysToDie_Data/Managed" ]]; then
  echo "GameDir not found: $GAME_DIR" >&2
  exit 1
fi
if [[ ! -d "$GAME_DIR/Mods/0_TFP_Harmony" ]]; then
  echo "ERROR: Mods/0_TFP_Harmony missing, do not delete it. Verify Steam files." >&2
  exit 1
fi

# Validate MAP_MODE before touching anything: a bad value must not destroy the
# previous install (validation used to run after rm -rf inside install_mod).
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

# The installed Config/realearth.json is generated through realearth.mod_config
# (MAP_MODE + product defaults); skipping it would silently install template
# defaults that ignore them, so python3 is a hard requirement.
if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 is required to write the installed mod config" >&2
  exit 1
fi

# Resolve client userdata via shipped helper (Proton Roaming preferred)
resolve_world_targets() {
  local tools_py="$ROOT/tools"
  if [[ -d "$tools_py/.venv" ]]; then
    # shellcheck disable=SC1091
    source "$tools_py/.venv/bin/activate"
  fi
  PYTHONPATH="$tools_py${PYTHONPATH:+:$PYTHONPATH}" python3 -m realearth.proton_paths
}

echo "Building RealEarth against: $GAME_DIR"
dotnet build "$ROOT/Source/RealEarth/RealEarth.csproj" -c Release -p:GameDir="$GAME_DIR"
DLL="$ROOT/Source/RealEarth/bin/Release/RealEarth.dll"
if [[ ! -f "$DLL" ]]; then
  echo "Build failed: no DLL" >&2
  exit 1
fi

install_mod() {
  local target="$1"
  local dest="$target/Mods/RealEarth"
  rm -rf "$dest"
  mkdir -p "$dest/Config" "$dest/Data"
  cp "$ROOT/ModInfo.xml" "$dest/"
  cp "$DLL" "$dest/"
  cp "$ROOT/Config/realearth.json" "$dest/Config/"
  [[ -f "$ROOT/Config/nav_objects.xml" ]] && cp -f "$ROOT/Config/nav_objects.xml" "$dest/Config/"
  # RealEarth YDim expand tools (part of this mod)
  mkdir -p "$dest/Tools"
  if [[ -f "$ROOT/tools/engine_patcher/bin/Release/EngineHeightPatcher.exe" ]]; then
    cp -f "$ROOT/tools/engine_patcher/bin/Release/EngineHeightPatcher.exe" "$dest/Tools/"
    [[ -f "$ROOT/tools/engine_patcher/bin/Release/Mono.Cecil.dll" ]] && \
      cp -f "$ROOT/tools/engine_patcher/bin/Release/Mono.Cecil.dll" "$dest/Tools/"
  fi
  if [[ -f "$ROOT/scripts/apply_engine_expand.sh" ]]; then
    cp -f "$ROOT/scripts/apply_engine_expand.sh" "$dest/Tools/"
    chmod +x "$dest/Tools/apply_engine_expand.sh"
  fi
  [[ -f "$ROOT/Config/realearth.advanced_height.json" ]] && \
    cp -f "$ROOT/Config/realearth.advanced_height.json" "$dest/Config/"

  # MAP_MODE validated up front (see top of script); Streamed is the 1:1 inject default
  local map_mode="$MAP_MODE"
  if [[ -d "$ROOT/data/samples/demo_region" ]]; then
    mkdir -p "$dest/Data/tiles"
    if ! cp -a "$ROOT/data/samples/demo_region/." "$dest/Data/tiles/"; then
      echo "WARN: demo tile copy failed into $dest/Data/tiles (Streamed will sample ocean until CDN configured)" >&2
    fi
    if [[ ! -f "$dest/Data/tiles/earth.manifest.json" ]]; then
      echo "WARN: no earth.manifest.json under $dest/Data/tiles, pack incomplete? Run make demo." >&2
    fi
  fi
  # Streamed takes world size, bbox and antimeridian wrap from the pack that
  # just landed in Data/tiles (docs/MODLET.md: wrap on full-planet canvases
  # only). Baked keeps the template canvas and never wraps.
  local canvas=(EnableLongitudeWrap=false)
  if [[ "${map_mode,,}" == "streamed" ]]; then
    canvas=(--sync-manifest --sync-bbox --spawn-from-bbox --max-window "$LOCAL_WINDOW_SIZE")
  fi
  # Height: RealEarth YDim expand is part of this mod (Tools/). StockSafe is a
  # fallback only, never the product path (docs/HEIGHT_LIMITS.md).
  PYTHONPATH="$ROOT/tools" python3 -m realearth.mod_config write "$dest" "$ROOT" \
    --template "$ROOT/Config/realearth.json" \
    "${canvas[@]}" \
    "MapMode=$map_mode" \
    SingleWorldSession=true \
    MultiplayerOriginMode=SoloSlide \
    "StreamRadiusTiles?=2" \
    "UnloadRadiusTiles?=4" \
    TilePackPath=Data/tiles \
    "DebugRevealFullMap?=false" \
    "EnableEngineHeightMod?=true" \
    "EngineHeightStockSafe?=false" \
    "EngineMaxGameY?=29000" \
    "EngineHeightOneToOne?=true" \
    "EngineHeightPreferVanillaCeiling?=false" \
    "LocalWindowSize?=$LOCAL_WINDOW_SIZE"
  echo "Installed mod → $dest (MapMode=${map_mode})"
}

install_mod "$GAME_DIR"
if [[ -d "$DS_DIR/Mods" ]]; then
  install_mod "$DS_DIR"
fi

WORLD_SRC="$ROOT/worlds/RealEarth"
if [[ ! -d "$WORLD_SRC" || ! -f "$WORLD_SRC/dtm.raw" ]]; then
  echo "WARN: no baked world at $WORLD_SRC, run bake-world first" >&2
else
  if ! command -v python3 >/dev/null; then
    echo "ERROR: python3 required to resolve world install targets" >&2
    exit 1
  fi
  mapfile -t RESOLVE < <(resolve_world_targets)
  PRIMARY=""
  PROTON_UD=""
  TARGETS=()
  for line in "${RESOLVE[@]}"; do
    case "$line" in
      PRIMARY\ *) PRIMARY="${line#PRIMARY }" ;;
      PROTON\ *) PROTON_UD="${line#PROTON }" ;;
      TARGET\ *) TARGETS+=("${line#TARGET }") ;;
    esac
  done
  if [[ "${#TARGETS[@]}" -eq 0 ]]; then
    echo "ERROR: no GeneratedWorlds install targets resolved (see resolve_world_targets output above)" >&2
    exit 1
  fi

  echo "Primary client userdata: $PRIMARY"
  if [[ -n "$PROTON_UD" ]]; then
    echo "Proton Roaming userdata: $PROTON_UD"
  else
    echo "WARN: Proton compatdata/251570 not found; falling back to native paths only"
  fi

  INSTALLED=()
  for gw in "${TARGETS[@]}"; do
    dest="$gw/RealEarth"
    mkdir -p "$gw"
    rm -rf "$dest"
    cp -a "$WORLD_SRC" "$dest"
    echo "Installed world → $dest"
    INSTALLED+=("$dest")
  done

  # Require Proton world when Proton is the play path
  if [[ -n "$PROTON_UD" ]]; then
    PROTON_WORLD="$PROTON_UD/GeneratedWorlds/RealEarth"
    if [[ ! -f "$PROTON_WORLD/dtm.raw" ]]; then
      echo "ERROR: Proton GeneratedWorld missing after install: $PROTON_WORLD" >&2
      exit 1
    fi
  fi
fi

echo
echo "=== Install summary ==="
echo "Client game:  $GAME_DIR"
echo "Mod:          $GAME_DIR/Mods/RealEarth/"
echo "Harmony kept: $GAME_DIR/Mods/0_TFP_Harmony/"
if [[ -n "${PROTON_UD:-}" ]]; then
  echo "Proton userdata (Windows client): $PROTON_UD"
  echo "World (Proton): $PROTON_UD/GeneratedWorlds/RealEarth"
fi
echo
echo "Play (Steam/Proton Windows client):"
echo "  1. Launch 7 Days to Die from Steam (Proton)"
echo "  2. MapMode=${MAP_MODE:-Streamed}:"
echo "       Streamed → host world size matching LocalWindowSize + Data/tiles .rte inject"
echo "       Baked    → New Game → World: RealEarth (GeneratedWorlds DTM)"
echo "     Override: MAP_MODE=Baked $0"
echo "  3. Log under Proton: .../compatdata/251570/.../7DaysToDie/logs/"
echo "     look for: [RealEarth] RealEarth init OK and Streamed inject"
echo "EAC: disable if C# mods fail to load on your build."
