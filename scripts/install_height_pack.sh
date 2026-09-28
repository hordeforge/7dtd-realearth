#!/usr/bin/env bash
# Install a height-test tile pack into client and/or dedicated Mods/RealEarth without
# clobbering the wrong pack. Usage:
#   ./scripts/install_height_pack.sh h500
#   ./scripts/install_height_pack.sh everest
set -euo pipefail

usage() {
  # Header comment with the leading '# ' stripped; a fixed line range would
  # shift whenever a note is added above it.
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/generated-world.sh
source "$ROOT/scripts/generated-world.sh"
KIND="${1:-h500}"
GAME_DIR="${SEVENDTD_GAME_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days To Die}"
DS_DIR="${SEVENDTD_SERVER_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days to Die Dedicated Server}"
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

case "$KIND" in
  h500|500)
    PACK="$ROOT/data/samples/height_test_500"
    WORLD="$ROOT/worlds/RealEarth_H500"
    WORLD_NAME="RealEarth_H500"
    ENGINE_MAX=29000  # product ceiling (sea 16000 + airliner 12000 + headroom); fixture peak stays 500
    SPAWN_LON=0.025
    SPAWN_LAT=0.025
    ;;
  everest|height|full)
    PACK="$ROOT/data/samples/height_test"
    WORLD="$ROOT/worlds/RealEarth_HeightTest"
    WORLD_NAME="RealEarth_HeightTest"
    ENGINE_MAX=29000
    SPAWN_LON=86.925
    SPAWN_LAT=27.988
    ;;
  *)
    echo "Usage: $0 h500|everest" >&2
    exit 2
    ;;
esac

if [[ ! -d "$PACK" ]]; then
  echo "Pack missing: $PACK, generate first (make height-map-500 / height-map)" >&2
  exit 1
fi

if [[ ! -d "$GAME_DIR/Mods/0_TFP_Harmony" ]]; then
  echo "ERROR: $GAME_DIR/Mods/0_TFP_Harmony missing: RealEarth.dll cannot load without it. Verify Steam files." >&2
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
  [[ -f "$ROOT/Config/spawning.xml" ]] && cp -f "$ROOT/Config/spawning.xml" "$dest/Config/"
  [[ -f "$ROOT/Config/gamestages.xml" ]] && cp -f "$ROOT/Config/gamestages.xml" "$dest/Config/"
  [[ -f "$ROOT/Config/buffs.xml" ]] && cp -f "$ROOT/Config/buffs.xml" "$dest/Config/"
  if [[ -d "$ROOT/Config/XUi_InGame" ]]; then
    mkdir -p "$dest/Config/XUi_InGame"
    cp -f "$ROOT/Config/XUi_InGame/"*.xml "$dest/Config/XUi_InGame/" 2>/dev/null || true
  fi
  cp -f "$ROOT/ModInfo.xml" "$dest/"
  cp -f "$DLL" "$dest/"
  # The mod folder is redistributed standalone; MIT requires the license text.
  cp -f "$ROOT/LICENSE" "$dest/"
  rm -rf "$dest/Data/tiles"
  mkdir -p "$dest/Data/tiles"
  if [[ -d "$PACK/tiles" ]]; then
    mkdir -p "$dest/Data/tiles/tiles"
    cp -a "$PACK/tiles/." "$dest/Data/tiles/tiles/"
  fi
  for n in earth.manifest.json height_test.json settlements.json cities.json preview_elev_m.png; do
    [[ -f "$PACK/$n" ]] && cp -f "$PACK/$n" "$dest/Data/tiles/"
  done
  # Fresh config (no repo template): this pack defines its own standalone setup.
  PYTHONPATH="$ROOT/tools" python3 -m realearth.mod_config write "$dest" "$ROOT" \
    --fresh --sync-manifest --sync-bbox \
    MapMode=Streamed \
    SingleWorldSession=true \
    EnableEngineHeightMod=true \
    "EngineHeightStockSafe=false" \
    EngineMaxGameY="$ENGINE_MAX" \
    EngineHeightOneToOne=true \
    "EngineHeightPreferVanillaCeiling=false" \
    FailClosedMissingTiles=true \
    TilePackPath=Data/tiles \
    WorldWidth=512 \
    WorldHeight=512 \
    TileSize=512 \
    LocalWindowSize=512 \
    EnableLongitudeWrap=false \
    DebugRevealFullMap=false \
    MultiplayerOriginMode=SharedFixed \
    SpawnLongitude="$SPAWN_LON" \
    SpawnLatitude="$SPAWN_LAT" \
    DefaultSpawnLon="$SPAWN_LON" \
    DefaultSpawnLat="$SPAWN_LAT"
}

install_one "$GAME_DIR"
install_one "$DS_DIR"

# Worlds for New Game / dedicated. Targets come from realearth.proton_paths,
# the same resolver install_proton.sh uses, so a Steam library outside the
# default ~/.local/share layout (or a STEAM_DIR override) is honoured instead of
# silently dropping the Proton client target.
if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 is required to resolve world install targets" >&2
  exit 1
fi
if [[ -d "$ROOT/tools/.venv" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/tools/.venv/bin/activate"
fi
mapfile -t RESOLVE < <(PYTHONPATH="$ROOT/tools${PYTHONPATH:+:$PYTHONPATH}" python3 -m realearth.proton_paths)
WORLD_TARGETS=()
for line in "${RESOLVE[@]}"; do
  case "$line" in
    TARGET\ *) WORLD_TARGETS+=("${line#TARGET }") ;;
  esac
done
# The dedicated test runs out of a cache userdata, not a Steam tree.
WORLD_TARGETS+=("$HOME/.cache/realearth-dedicated/GeneratedWorlds")

INSTALLED_WORLDS=0
if [[ -d "$WORLD" ]]; then
  for gw in "${WORLD_TARGETS[@]}"; do
    install_generated_world "$WORLD" "$gw" "$WORLD_NAME"
    INSTALLED_WORLDS=$((INSTALLED_WORLDS + 1))
  done
fi

if [[ ! -d "$WORLD" ]]; then
  echo "WARN: baked world missing: $WORLD, run make height-map / height-map-500 first" >&2
elif (( INSTALLED_WORLDS == 0 )); then
  echo "WARN: world $WORLD_NAME not installed to any GeneratedWorlds target (all missing)" >&2
fi

echo "OK pack=$KIND installed to client+dedicated Mods/RealEarth (world targets hit: $INSTALLED_WORLDS)"
echo "Play client: New Game → $WORLD_NAME"
echo "Dedicated: set GameWorld=$WORLD_NAME or run make dedicated-height-test"
