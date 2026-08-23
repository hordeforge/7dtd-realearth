#!/usr/bin/env bash
# Install a height-test tile pack into client and/or dedicated Mods/RealEarth without
# clobbering the wrong pack. Usage:
#   ./scripts/install_height_pack.sh h500
#   ./scripts/install_height_pack.sh everest
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KIND="${1:-h500}"
GAME_DIR="${SEVENDTD_GAME_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days To Die}"
DS_DIR="${SEVENDTD_SERVER_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days to Die Dedicated Server}"
DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.cache/dotnet-sdk}"
export PATH="${DOTNET_ROOT}:${PATH}"

case "$KIND" in
  h500|500)
    PACK="$ROOT/data/samples/height_test_500"
    WORLD="$ROOT/worlds/RealEarth_H500"
    WORLD_NAME="RealEarth_H500"
    ENGINE_MAX=11000  # engine ceiling Everest-ready; map peak still 500
    SPAWN_LON=0.025
    SPAWN_LAT=0.025
    ;;
  everest|height|full)
    PACK="$ROOT/data/samples/height_test"
    WORLD="$ROOT/worlds/RealEarth_HeightTest"
    WORLD_NAME="RealEarth_HeightTest"
    ENGINE_MAX=11000
    SPAWN_LON=86.925
    SPAWN_LAT=27.988
    ;;
  *)
    echo "Usage: $0 h500|everest" >&2
    exit 2
    ;;
esac

if [[ ! -d "$PACK" ]]; then
  echo "Pack missing: $PACK — generate first (make height-map-500 / height-map)" >&2
  exit 1
fi

dotnet build "$ROOT/Source/RealEarth/RealEarth.csproj" -c Release -p:GameDir="$GAME_DIR" -v q
DLL="$ROOT/Source/RealEarth/bin/Release/RealEarth.dll"
test -f "$DLL"

install_one() {
  local target="$1"
  [[ -d "$target" ]] || return 0
  local dest="$target/Mods/RealEarth"
  mkdir -p "$dest/Config" "$dest/Data/tiles"
  [[ -f "$ROOT/Config/nav_objects.xml" ]] && cp -f "$ROOT/Config/nav_objects.xml" "$dest/Config/"
  cp -f "$ROOT/ModInfo.xml" "$dest/"
  cp -f "$DLL" "$dest/"
  rm -rf "$dest/Data/tiles"
  mkdir -p "$dest/Data/tiles"
  if [[ -d "$PACK/tiles" ]]; then
    mkdir -p "$dest/Data/tiles/tiles"
    cp -a "$PACK/tiles/." "$dest/Data/tiles/tiles/"
  fi
  for n in earth.manifest.json height_test.json settlements.json cities.json preview_elev_m.png; do
    [[ -f "$PACK/$n" ]] && cp -f "$PACK/$n" "$dest/Data/tiles/"
  done
  python3 - <<PY
import json
from pathlib import Path
dest = Path("$dest")
cfg = {
    "MapMode": "Streamed",
    "SingleWorldSession": True,
    "EnableEngineHeightMod": True,
    # Still StockSafe=true so stock DLL stays playable; expand auto-enables 1:1
    "EngineHeightStockSafe": True,
    "EngineMaxGameY": int("$ENGINE_MAX"),
    "EngineHeightOneToOne": True,
    "EngineHeightPreferVanillaCeiling": False,
    "TilePackPath": "Data/tiles",
    "WorldWidth": 512,
    "WorldHeight": 512,
    "TileSize": 512,
    "LocalWindowSize": 512,
    "EnableLongitudeWrap": False,
    "DebugRevealFullMap": False,
    "MultiplayerOriginMode": "SharedFixed",
    "SpawnLongitude": float("$SPAWN_LON"),
    "SpawnLatitude": float("$SPAWN_LAT"),
    "DefaultSpawnLon": float("$SPAWN_LON"),
    "DefaultSpawnLat": float("$SPAWN_LAT"),
}
man = dest / "Data" / "tiles" / "earth.manifest.json"
if man.is_file():
    m = json.loads(man.read_text(encoding="utf-8"))
    cfg["WorldWidth"] = int(m.get("world_width") or 512)
    cfg["WorldHeight"] = int(m.get("world_height") or 512)
    cfg["TileSize"] = int(m.get("tile_size") or 512)
    cfg["LocalWindowSize"] = min(cfg["WorldWidth"], cfg["WorldHeight"])
    bbox = m.get("bbox") or {}
    if bbox:
        cfg["BboxWest"] = float(bbox["west"])
        cfg["BboxSouth"] = float(bbox["south"])
        cfg["BboxEast"] = float(bbox["east"])
        cfg["BboxNorth"] = float(bbox["north"])
(dest / "Config" / "realearth.json").write_text(json.dumps(cfg, indent=2) + "\n")
print(f"Installed pack → {dest} EngineMaxGameY={cfg['EngineMaxGameY']}")
PY
}

install_one "$GAME_DIR"
install_one "$DS_DIR"

# Worlds for New Game / dedicated
for gw in \
  "$HOME/.local/share/Steam/steamapps/compatdata/251570/pfx/drive_c/users/steamuser/AppData/Roaming/7DaysToDie/GeneratedWorlds" \
  "$HOME/.local/share/7DaysToDie/GeneratedWorlds" \
  "$HOME/.cache/realearth-dedicated/GeneratedWorlds"
do
  if [[ -d "$WORLD" ]]; then
    mkdir -p "$gw"
    rm -rf "${gw:?}/$WORLD_NAME"
    cp -a "$WORLD" "$gw/$WORLD_NAME"
    echo "World → $gw/$WORLD_NAME"
  fi
done

echo "OK pack=$KIND world=$WORLD_NAME"
echo "Play client: New Game → $WORLD_NAME"
echo "Dedicated: set GameWorld=$WORLD_NAME or run make dedicated-height-test"
