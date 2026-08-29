#!/usr/bin/env bash
# Start RealEarth dedicated with minimal network surface:
#   EAC off, crossplay off, SteamNetworking off (LiteNetLib only),
#   not listed, Twitch locked, no web dashboard.
# Leaves the server running (does not auto-kill after soak).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GAME_DIR="${SEVENDTD_GAME_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days To Die}"
DS_DIR="${SEVENDTD_SERVER_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days to Die Dedicated Server}"
USERDATA="${RE_DEDICATED_USERDATA:-$HOME/.cache/realearth-dedicated}"
CONFIG_SRC="$ROOT/scripts/serverconfig_height_test.xml"
WORLD_NAME="${RE_WORLD_NAME:-RealEarth_H500}"
# WORLD_NAME lands in rm -rf targets and generated configs: restrict it to a
# single plain directory name so it cannot traverse or break quoting.
case "$WORLD_NAME" in
  ""|*[!A-Za-z0-9._-]*|[!A-Za-z0-9]*)
    echo "ERROR: RE_WORLD_NAME must be a plain directory name ([A-Za-z0-9._-], leading alnum; got: $WORLD_NAME)" >&2
    exit 1
    ;;
esac
MAX_PLAYERS="${RE_SERVER_MAX_PLAYERS:-1024}"
case "$MAX_PLAYERS" in
  ""|*[!0-9]*|0)
    echo "ERROR: RE_SERVER_MAX_PLAYERS must be a positive integer (got: $MAX_PLAYERS)" >&2
    exit 1
    ;;
esac
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

if [[ ! -x "$DS_DIR/7DaysToDieServer.x86_64" ]]; then
  echo "ERROR: dedicated server not found: $DS_DIR" >&2
  exit 1
fi
if [[ ! -f "$CONFIG_SRC" ]]; then
  echo "ERROR: missing $CONFIG_SRC" >&2
  exit 1
fi

echo "=== RealEarth minimal dedicated ==="
echo "Server:   $DS_DIR"
echo "UserData: $USERDATA"
echo "World:    $WORLD_NAME"
echo "MaxPlayers=$MAX_PLAYERS  EAC=off Crossplay=off SteamNetworking=off Visibility=0 Telnet=off"

# Local load tests need crossplatform=None (EOS session never initializes → ServerState kicks)
# and Local on serverplatforms so simulated clients can auth without Steam tickets.
PCFG="$DS_DIR/platform.cfg"
if [[ -f "$PCFG" ]]; then
  if [[ ! -f "$PCFG.re-bak" ]]; then
    cp "$PCFG" "$PCFG.re-bak"
  fi
  cat >"$PCFG" <<'EOF'
platform=Steam
crossplatform=None
serverplatforms=Steam,LAN,Local,
EOF
  echo "platform.cfg → Steam/None + Local serverplatform (backup: platform.cfg.re-bak)"
fi

# Stop previous dedicated by /proc exe path (pgrep -x truncates long names).
# Match only servers under THIS install dir so unrelated 7DTD servers on a
# shared host are never signalled.
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  [[ -L "$d/exe" ]] || continue
  exe=$(readlink "$d/exe" 2>/dev/null || true)
  case "$exe" in
    "$DS_DIR"/*7DaysToDieServer.x86_64)
      kill "$pid" 2>/dev/null || true
      ;;
  esac
done
sleep 2
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  [[ -L "$d/exe" ]] || continue
  exe=$(readlink "$d/exe" 2>/dev/null || true)
  case "$exe" in "$DS_DIR"/*7DaysToDieServer.x86_64) kill -9 "$pid" 2>/dev/null || true ;; esac
done
sleep 1

# YDim expand + mod install (same as height test path)
export SEVENDTD_GAME_DIR="$GAME_DIR"
export SEVENDTD_SERVER_DIR="$DS_DIR"
chmod +x "$ROOT/scripts/patch_engine_height.sh"
"$ROOT/scripts/patch_engine_height.sh" --force

dotnet build "$ROOT/Source/RealEarth/RealEarth.csproj" -c Release -p:GameDir="$GAME_DIR" -v q
DLL="$ROOT/Source/RealEarth/bin/Release/RealEarth.dll"
test -f "$DLL"

install_mod() {
  local target="$1"
  local dest="$target/Mods/RealEarth"
  mkdir -p "$dest/Config" "$dest/Data/tiles"
  cp -f "$ROOT/ModInfo.xml" "$dest/"
  [[ -f "$ROOT/Config/nav_objects.xml" ]] && cp -f "$ROOT/Config/nav_objects.xml" "$dest/Config/"
  cp -f "$DLL" "$dest/"
  # Pack selection: RE_SCENARIO_PACK=everest forces the Everest height_test
  # pack (same convention as run_dedicated_height_test.sh and the sibling
  # 7dtd-loadgen); default prefers the staged H500 pack.
  local pack="$ROOT/data/samples/height_test_500"
  if [[ "${RE_SCENARIO_PACK:-}" == "everest" ]]; then
    pack="$ROOT/data/samples/height_test"
  fi
  [[ -d "$pack/tiles" ]] || pack="$ROOT/data/samples/height_test"
  if [[ -d "$pack/tiles" ]]; then
    rm -rf "$dest/Data/tiles"
    mkdir -p "$dest/Data/tiles/tiles"
    if ! cp -a "$pack/tiles/." "$dest/Data/tiles/tiles/" 2>/dev/null; then
      echo "WARN: tile copy failed into $dest/Data/tiles (dedicated will sample ocean)" >&2
    fi
    for n in earth.manifest.json height_test.json settlements.json cities.json; do
      [[ -f "$pack/$n" ]] && cp -f "$pack/$n" "$dest/Data/tiles/"
    done
  fi
  PYTHONPATH="$ROOT/tools" python3 -m realearth.mod_config write "$dest" "$ROOT" --sync-manifest \
    MapMode=Streamed \
    SingleWorldSession=true \
    EnableEngineHeightMod=true \
    EngineMaxGameY=11000 \
    MultiplayerOriginMode=SharedFixed \
    TilePackPath=Data/tiles \
    WorldWidth=512 \
    WorldHeight=512 \
    TileSize=512 \
    LocalWindowSize=512 \
    EnableLongitudeWrap=false
  echo "mod → $dest"
}
install_mod "$GAME_DIR"
install_mod "$DS_DIR"
if [[ ! -d "$DS_DIR/Mods/0_TFP_Harmony" && -d "$GAME_DIR/Mods/0_TFP_Harmony" ]]; then
  cp -a "$GAME_DIR/Mods/0_TFP_Harmony" "$DS_DIR/Mods/"
fi

mkdir -p "$USERDATA/GeneratedWorlds" "$USERDATA/Saves"
if [[ -d "$ROOT/worlds/$WORLD_NAME" ]]; then
  rm -rf "$USERDATA/GeneratedWorlds/$WORLD_NAME"
  cp -a "$ROOT/worlds/$WORLD_NAME" "$USERDATA/GeneratedWorlds/$WORLD_NAME"
fi

# Write live serverconfig (minimal network surface + UserDataFolder + max players)
TMPCFG="$USERDATA/serverconfig_height_test.xml"
# Minimal network surface forced even if the template drifts (server_config
# inserts a property the template lost instead of skipping it). Bots need world
# threats, so zombies spawn and move during the day.
PYTHONPATH="$ROOT/tools" python3 -m realearth.server_config \
  "$CONFIG_SRC" "$TMPCFG" --userdata "$USERDATA" \
  "GameWorld=$WORLD_NAME" \
  "ServerMaxPlayerCount=$MAX_PLAYERS" \
  EACEnabled=false \
  ServerAllowCrossplay=false \
  ServerDisabledNetworkProtocols=SteamNetworking \
  ServerVisibility=0 \
  TwitchServerPermission=1000 \
  TwitchBloodMoonAllowed=false \
  WebDashboardEnabled=false \
  IgnoreEOSSanctions=true \
  EnemySpawnMode=true \
  ZombieMove=2

# Discord: not a serverconfig property. Write a local UserOptions override if present.
OPTS="$USERDATA/UserOptions.ini"
if [[ ! -f "$OPTS" ]]; then
  printf '%s\n' \
    '[General]' \
    'DiscordDisabled=true' \
    >"$OPTS"
else
  if grep -q 'DiscordDisabled' "$OPTS"; then
    sed -i 's/^DiscordDisabled=.*/DiscordDisabled=true/' "$OPTS"
  else
    printf '\nDiscordDisabled=true\n' >>"$OPTS"
  fi
fi
echo "UserOptions DiscordDisabled=true → $OPTS"

LOG="$USERDATA/server_minimal_$(date -u +%Y-%m-%d__%H-%M-%S)_$$.txt"
cd "$DS_DIR"
export LD_LIBRARY_PATH="."
./7DaysToDieServer.x86_64 \
  -logfile "$LOG" \
  -quit -batchmode -nographics -dedicated \
  -configfile="$TMPCFG" \
  >"$USERDATA/server_stdout_minimal.txt" 2>&1 &
SPID=$!
echo "PID=$SPID"
echo "Log=$LOG"
echo "$SPID" >"$USERDATA/dedicated.pid"
echo "$LOG" >"$USERDATA/dedicated.logpath"

# Wait until LiteNetLib is up
READY=0
for _ in $(seq 1 90); do
  if ! kill -0 "$SPID" 2>/dev/null; then
    echo "ERROR: server exited early" >&2
    tail -40 "$LOG" 2>/dev/null || true
    exit 1
  fi
  if [[ -f "$LOG" ]] && grep -q "LiteNetLib server started" "$LOG" 2>/dev/null \
    && grep -Eq "createWorld\(\) done|StartGame done" "$LOG" 2>/dev/null; then
    echo "OK: dedicated ready (LiteNetLib + world loaded)"
    READY=1
    break
  fi
  sleep 2
done
if (( READY != 1 )); then
  echo "ERROR: server not ready after 180s (LiteNetLib/world-load markers missing)" >&2
  tail -40 "$LOG" 2>/dev/null || true
  exit 1
fi

echo "======== network prefs from log ========"
grep -En "EACEnabled|Crossplay|ServerDisabledNetwork|ServerVisibility|Twitch|Discord|LiteNetLib server|EOS|SteamNetworking" "$LOG" 2>/dev/null | head -40 || true
echo "======== listening UDP ========"
ss -ulnp 2>/dev/null | grep -E '2690|7Days' || true
echo
echo "Server left running. Stop with: kill \$(cat $USERDATA/dedicated.pid)"
echo "Load-test bots (sibling project): cd ../7dtd-loadgen && make join"
echo "  7dtd-loadgen --join --host 127.0.0.1 --port 26902 --count 8"
