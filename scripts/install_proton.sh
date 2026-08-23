#!/usr/bin/env bash
# Install RealEarth mod + GeneratedWorld into Steam/Proton Windows 7DTD.
# World data goes into the Proton Windows Roaming folder (NOT native ~/.local/share).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GAME_DIR="${SEVENDTD_GAME_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days To Die}"
DS_DIR="${SEVENDTD_SERVER_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days to Die Dedicated Server}"
# Locate a .NET SDK: explicit env, then the usual local caches (mirrors Makefile).
find_dotnet_root() {
  for d in "$DOTNET_ROOT" "$HOME/.cache/dotnet-sdk" "$HOME/.dotnet" \
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
  echo "ERROR: Mods/0_TFP_Harmony missing — do not delete it. Verify Steam files." >&2
  exit 1
fi

# Resolve client userdata via shipped helper (Proton Roaming preferred)
resolve_world_targets() {
  local tools_py="$ROOT/tools"
  if [[ -d "$tools_py/.venv" ]]; then
    # shellcheck disable=SC1091
    source "$tools_py/.venv/bin/activate"
  fi
  PYTHONPATH="$tools_py${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
from realearth.proton_paths import (
    client_generated_worlds_targets,
    primary_client_userdata,
    proton_userdata,
)
print("PRIMARY", primary_client_userdata())
print("PROTON", proton_userdata() or "")
for t in client_generated_worlds_targets(prefer_proton=True, also_native=True):
    print("TARGET", t)
PY
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

  # MAP_MODE=Streamed (default for 1:1 inject) or Baked (finite DTM world)
  local map_mode="${MAP_MODE:-Streamed}"
  if command -v python3 >/dev/null; then
    python3 - <<'PY' "$dest/Config/realearth.json" "$map_mode" "$ROOT/data/samples/demo_region"
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
map_mode = sys.argv[2]
demo = Path(sys.argv[3])
with open(p, encoding="utf-8") as f:
    cfg = json.load(f)
cfg["MapMode"] = map_mode
cfg["SingleWorldSession"] = True
cfg["MultiplayerOriginMode"] = "SoloSlide"
cfg["StreamRadiusTiles"] = int(cfg.get("StreamRadiusTiles") or 2)
cfg["UnloadRadiusTiles"] = int(cfg.get("UnloadRadiusTiles") or 4)
cfg["TilePackPath"] = "Data/tiles"
# Debug: full in-game map uncovered (not only visited places)
cfg["DebugRevealFullMap"] = bool(cfg.get("DebugRevealFullMap", False))
# Height: RealEarth YDim expand is part of this mod (Tools/). StockSafe = fallback only.
cfg["EnableEngineHeightMod"] = bool(cfg.get("EnableEngineHeightMod", True))
cfg["EngineHeightStockSafe"] = bool(cfg.get("EngineHeightStockSafe", True))
cfg["EngineMaxGameY"] = int(cfg.get("EngineMaxGameY") or 11000)
cfg["EngineHeightOneToOne"] = bool(cfg.get("EngineHeightOneToOne", True))
cfg["EngineHeightPreferVanillaCeiling"] = bool(
    cfg.get("EngineHeightPreferVanillaCeiling", False)
)
# Streamed: keep wrap on for full-planet; regional demo pack manifest overrides at runtime
if map_mode.lower() == "streamed":
    cfg["EnableLongitudeWrap"] = True
    cfg["LocalWindowSize"] = int(cfg.get("LocalWindowSize") or 1024)
    # Prefer demo pack dimensions when present so Streamed samples resolve
    man = demo / "earth.manifest.json"
    if man.is_file():
        m = json.loads(man.read_text(encoding="utf-8"))
        if int(m.get("world_width") or 0) > 0:
            cfg["WorldWidth"] = int(m["world_width"])
            cfg["WorldHeight"] = int(m["world_height"])
            cfg["TileSize"] = int(m.get("tile_size") or 512)
            cfg["LocalWindowSize"] = min(cfg["LocalWindowSize"], cfg["WorldWidth"], cfg["WorldHeight"])
            # regional demo: no antimeridian wrap on small canvas
            if cfg["WorldWidth"] < 10_000_000:
                cfg["EnableLongitudeWrap"] = False
            bbox = m.get("bbox") or {}
            if bbox:
                cfg["BboxWest"] = float(bbox["west"])
                cfg["BboxSouth"] = float(bbox["south"])
                cfg["BboxEast"] = float(bbox["east"])
                cfg["BboxNorth"] = float(bbox["north"])
                cfg["DefaultSpawnLon"] = (cfg["BboxWest"] + cfg["BboxEast"]) * 0.5
                cfg["DefaultSpawnLat"] = (cfg["BboxSouth"] + cfg["BboxNorth"]) * 0.5
else:
    cfg["EnableLongitudeWrap"] = False
    cfg["LocalWindowSize"] = int(cfg.get("LocalWindowSize") or 1024)
with open(p, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print(f"Config MapMode={map_mode}")
PY
  fi
  if [[ -d "$ROOT/data/samples/demo_region" ]]; then
    mkdir -p "$dest/Data/tiles"
    cp -a "$ROOT/data/samples/demo_region/." "$dest/Data/tiles/" || true
  fi
  echo "Installed mod → $dest (MapMode=${map_mode})"
}

install_mod "$GAME_DIR"
if [[ -d "$DS_DIR/Mods" ]]; then
  install_mod "$DS_DIR"
fi

WORLD_SRC="$ROOT/worlds/RealEarth"
if [[ ! -d "$WORLD_SRC" || ! -f "$WORLD_SRC/dtm.raw" ]]; then
  echo "WARN: no baked world at $WORLD_SRC — run bake-world first" >&2
else
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
