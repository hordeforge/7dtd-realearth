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
MAX_PLAYERS="${RE_SERVER_MAX_PLAYERS:-1024}"
DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.cache/dotnet-sdk}"
export PATH="${DOTNET_ROOT}:${PATH}"
export DOTNET_ROOT

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

# Stop previous dedicated by /proc exe path (pgrep -x truncates long names)
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  [[ -L "$d/exe" ]] || continue
  exe=$(readlink "$d/exe" 2>/dev/null || true)
  case "$exe" in
    *7DaysToDieServer.x86_64)
      kill "$pid" 2>/dev/null || true
      ;;
  esac
done
sleep 2
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  [[ -L "$d/exe" ]] || continue
  exe=$(readlink "$d/exe" 2>/dev/null || true)
  case "$exe" in *7DaysToDieServer.x86_64) kill -9 "$pid" 2>/dev/null || true ;; esac
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
  local pack="$ROOT/data/samples/height_test_500"
  [[ -d "$pack/tiles" ]] || pack="$ROOT/data/samples/height_test"
  if [[ -d "$pack/tiles" ]]; then
    rm -rf "$dest/Data/tiles"
    mkdir -p "$dest/Data/tiles/tiles"
    cp -a "$pack/tiles/." "$dest/Data/tiles/tiles/" 2>/dev/null || true
    for n in earth.manifest.json height_test.json settlements.json cities.json; do
      [[ -f "$pack/$n" ]] && cp -f "$pack/$n" "$dest/Data/tiles/"
    done
  fi
  python3 - <<PY
import json
from pathlib import Path
cfg_path = Path("$dest/Config/realearth.json")
root = Path("$ROOT")
src_mp = root / "Config" / "realearth.mp.json"
src = root / "Config" / "realearth.json"
if src_mp.is_file():
    cfg = json.loads(src_mp.read_text(encoding="utf-8"))
elif src.is_file():
    cfg = json.loads(src.read_text(encoding="utf-8"))
else:
    cfg = {}
cfg.update({
    "MapMode": "Streamed",
    "SingleWorldSession": True,
    "EnableEngineHeightMod": True,
    "EngineMaxGameY": 11000,
    "MultiplayerOriginMode": "SharedFixed",
    "TilePackPath": "Data/tiles",
    "WorldWidth": 512,
    "WorldHeight": 512,
    "TileSize": 512,
    "LocalWindowSize": 512,
    "EnableLongitudeWrap": False,
})
man = Path("$dest/Data/tiles/earth.manifest.json")
if man.is_file():
    m = json.loads(man.read_text(encoding="utf-8"))
    cfg["WorldWidth"] = int(m.get("world_width") or 512)
    cfg["WorldHeight"] = int(m.get("world_height") or 512)
    cfg["TileSize"] = int(m.get("tile_size") or 512)
    cfg["LocalWindowSize"] = min(cfg["WorldWidth"], cfg["WorldHeight"])
cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print(f"mod → $dest")
PY
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
python3 - <<PY
from pathlib import Path
import re
src = Path("$CONFIG_SRC").read_text(encoding="utf-8")
ud = str(Path("$USERDATA").resolve())
if 'name="UserDataFolder"' not in src:
    src = src.replace(
        "<ServerSettings>",
        f'<ServerSettings>\n\t<property name="UserDataFolder" value="{ud}"/>',
    )
else:
    src = re.sub(
        r'name="UserDataFolder"\s*value="[^"]*"',
        f'name="UserDataFolder" value="{ud}"',
        src,
    )
src = re.sub(
    r'name="GameWorld"\s*value="[^"]*"',
    f'name="GameWorld" value="$WORLD_NAME"',
    src,
)
src = re.sub(
    r'name="ServerMaxPlayerCount"\s*value="[^"]*"',
    f'name="ServerMaxPlayerCount" value="$MAX_PLAYERS"',
    src,
)
# Force minimal network surface even if template drifts
src = re.sub(
    r'name="EACEnabled"\s*value="[^"]*"',
    'name="EACEnabled" value="false"',
    src,
)
src = re.sub(
    r'name="ServerAllowCrossplay"\s*value="[^"]*"',
    'name="ServerAllowCrossplay" value="false"',
    src,
)
src = re.sub(
    r'name="ServerDisabledNetworkProtocols"\s*value="[^"]*"',
    'name="ServerDisabledNetworkProtocols" value="SteamNetworking"',
    src,
)
src = re.sub(
    r'name="ServerVisibility"\s*value="[^"]*"',
    'name="ServerVisibility" value="0"',
    src,
)
src = re.sub(
    r'name="TwitchServerPermission"\s*value="[^"]*"',
    'name="TwitchServerPermission" value="1000"',
    src,
)
src = re.sub(
    r'name="TwitchBloodMoonAllowed"\s*value="[^"]*"',
    'name="TwitchBloodMoonAllowed" value="false"',
    src,
)
src = re.sub(
    r'name="WebDashboardEnabled"\s*value="[^"]*"',
    'name="WebDashboardEnabled" value="false"',
    src,
)
src = re.sub(
    r'name="IgnoreEOSSanctions"\s*value="[^"]*"',
    'name="IgnoreEOSSanctions" value="true"',
    src,
)
# Bots need world threats: zombies must spawn and move during day.
src = re.sub(
    r'name="EnemySpawnMode"\s*value="[^"]*"',
    'name="EnemySpawnMode" value="true"',
    src,
)
src = re.sub(
    r'name="ZombieMove"\s*value="[^"]*"',
    'name="ZombieMove" value="2"',
    src,
)
Path("$TMPCFG").write_text(src, encoding="utf-8")
print(f"Config → $TMPCFG")
# print key network settings
for line in src.splitlines():
    if any(k in line for k in (
        "EACEnabled", "Crossplay", "DisabledNetwork", "Visibility",
        "Twitch", "WebDashboard", "IgnoreEOS", "MaxPlayer",
        "EnemySpawnMode", "ZombieMove",
    )):
        print(" ", line.strip())
PY

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

LOG="$USERDATA/server_minimal_$(date +%Y-%m-%d__%H-%M-%S).txt"
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
for _ in $(seq 1 90); do
  if ! kill -0 "$SPID" 2>/dev/null; then
    echo "ERROR: server exited early" >&2
    tail -40 "$LOG" 2>/dev/null || true
    exit 1
  fi
  if [[ -f "$LOG" ]] && grep -q "LiteNetLib server started" "$LOG" 2>/dev/null \
    && grep -Eq "createWorld\(\) done|StartGame done" "$LOG" 2>/dev/null; then
    echo "OK: dedicated ready (LiteNetLib + world loaded)"
    break
  fi
  sleep 2
done

echo "======== network prefs from log ========"
grep -En "EACEnabled|Crossplay|ServerDisabledNetwork|ServerVisibility|Twitch|Discord|LiteNetLib server|EOS|SteamNetworking" "$LOG" 2>/dev/null | head -40 || true
echo "======== listening UDP ========"
ss -ulnp 2>/dev/null | grep -E '2690|7Days' || true
echo
echo "Server left running. Stop with: kill \$(cat $USERDATA/dedicated.pid)"
echo "Load-test bots (sibling project): cd ../7dtd-loadgen && make join"
echo "  7dtd-loadgen --join --host 127.0.0.1 --port 26902 --count 8"
