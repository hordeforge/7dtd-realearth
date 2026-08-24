#!/usr/bin/env bash
# Dedicated on a stock TFP prefab world OR RWG-generated map for bot POI/sleeper tests.
# Vanilla terrain (RealEarth mod disabled). LiteNetLib-only, EAC off, telnet off.
#
# Defaults: RWG 4096 (true 4k, loads faster than 6k/8k pregens, full prefab/sleeper pipeline).
#
#   # 4k RWG (default)
#   ./scripts/start_dedicated_prefab.sh
#
#   # Stock 6k pregen
#   RE_WORLD_NAME=Pregen06k01 ./scripts/start_dedicated_prefab.sh
#
#   # Stock Navezgane
#   RE_WORLD_NAME=Navezgane ./scripts/start_dedicated_prefab.sh
#
#   # Custom RWG size/seed
#   RE_WORLD_NAME=RWG RE_WORLD_GEN_SIZE=4096 RE_WORLD_GEN_SEED=botpoi4k ./scripts/start_dedicated_prefab.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DS_DIR="${SEVENDTD_SERVER_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days to Die Dedicated Server}"
USERDATA="${RE_DEDICATED_USERDATA:-$HOME/.cache/realearth-dedicated}"
# RWG = generate; otherwise must exist under Data/Worlds/
WORLD_NAME="${RE_WORLD_NAME:-RWG}"
# WORLD_NAME lands in generated configs and the Data/Worlds path: restrict it
# to a single plain directory name so it cannot traverse or break quoting.
case "$WORLD_NAME" in
  ""|*[!A-Za-z0-9._-]*|[!A-Za-z0-9]*)
    echo "ERROR: RE_WORLD_NAME must be a plain directory name ([A-Za-z0-9._-], leading alnum; got: $WORLD_NAME)" >&2
    exit 1
    ;;
esac
WORLD_GEN_SIZE="${RE_WORLD_GEN_SIZE:-4096}"
case "$WORLD_GEN_SIZE" in
  ""|*[!0-9]*|0)
    echo "ERROR: RE_WORLD_GEN_SIZE must be a positive integer (got: $WORLD_GEN_SIZE)" >&2
    exit 1
    ;;
esac
WORLD_GEN_SEED="${RE_WORLD_GEN_SEED:-botpoi4k}"
GAME_NAME="${RE_GAME_NAME:-BotPoi_${WORLD_NAME}_${WORLD_GEN_SIZE}}"
MAX_PLAYERS="${RE_SERVER_MAX_PLAYERS:-64}"
case "$MAX_PLAYERS" in
  ""|*[!0-9]*|0)
    echo "ERROR: RE_SERVER_MAX_PLAYERS must be a positive integer (got: $MAX_PLAYERS)" >&2
    exit 1
    ;;
esac
CONFIG_SRC="$ROOT/scripts/serverconfig_height_test.xml"

if [[ ! -x "$DS_DIR/7DaysToDieServer.x86_64" ]]; then
  echo "ERROR: dedicated server not found: $DS_DIR" >&2
  exit 1
fi

pref_count="n/a (RWG generates on first boot)"
if [[ "$WORLD_NAME" != "RWG" ]]; then
  WORLD_DIR="$DS_DIR/Data/Worlds/$WORLD_NAME"
  if [[ ! -d "$WORLD_DIR" ]]; then
    echo "ERROR: stock world not found: $WORLD_DIR" >&2
    echo "Available:" >&2
    ls -1 "$DS_DIR/Data/Worlds" 2>/dev/null || true
    exit 1
  fi
  if [[ -f "$WORLD_DIR/prefabs.xml" ]]; then
    # grep -c prints "0" AND exits 1 on no match; `|| echo 0` would append a
    # second zero. Suppress stderr, keep stdout, fall back via default value.
    pref_count=$(grep -c "<decoration" "$WORLD_DIR/prefabs.xml" 2>/dev/null)
    pref_count=${pref_count:-0}
  fi
fi

echo "=== Dedicated prefab / RWG world (POI/sleeper) ==="
echo "Server:   $DS_DIR"
echo "UserData: $USERDATA"
echo "World:    $WORLD_NAME  genSize=$WORLD_GEN_SIZE  seed=$WORLD_GEN_SEED"
echo "          prefabs≈$pref_count  GameName=$GAME_NAME  MaxPlayers=$MAX_PLAYERS"

# Local loadtest bot auth (7dtd-loadgen)
PCFG="$DS_DIR/platform.cfg"
if [[ -f "$PCFG" ]]; then
  [[ -f "$PCFG.re-bak" ]] || cp "$PCFG" "$PCFG.re-bak"
  cat >"$PCFG" <<'EOF'
platform=Steam
crossplatform=None
serverplatforms=Steam,LAN,Local,
EOF
fi

# Stop previous dedicated. Match only servers under THIS install dir so
# unrelated 7DTD servers on a shared host are never signalled.
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  [[ -L "$d/exe" ]] || continue
  exe=$(readlink "$d/exe" 2>/dev/null || true)
  case "$exe" in "$DS_DIR"/*7DaysToDieServer.x86_64) kill "$pid" 2>/dev/null || true ;; esac
done
sleep 2
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  [[ -L "$d/exe" ]] || continue
  exe=$(readlink "$d/exe" 2>/dev/null || true)
  case "$exe" in "$DS_DIR"/*7DaysToDieServer.x86_64) kill -9 "$pid" 2>/dev/null || true ;; esac
done
sleep 1

# Disable RealEarth mod for pure stock/RWG terrain
if [[ -d "$DS_DIR/Mods/RealEarth" ]]; then
  rm -rf "$DS_DIR/Mods/RealEarth.off"
  mv "$DS_DIR/Mods/RealEarth" "$DS_DIR/Mods/RealEarth.off"
  echo "RealEarth mod → Mods/RealEarth.off"
fi

mkdir -p "$USERDATA/Saves" "$USERDATA/Logs" "$USERDATA/GeneratedWorlds"
TMPCFG="$USERDATA/serverconfig_prefab.xml"
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
    src = re.sub(r'name="UserDataFolder"\s*value="[^"]*"', f'name="UserDataFolder" value="{ud}"', src)
repls = {
    "GameWorld": "$WORLD_NAME",
    "GameName": "$GAME_NAME",
    "WorldGenSeed": "$WORLD_GEN_SEED",
    "WorldGenSize": "$WORLD_GEN_SIZE",
    "ServerMaxPlayerCount": "$MAX_PLAYERS",
    "EACEnabled": "false",
    "ServerAllowCrossplay": "false",
    "ServerDisabledNetworkProtocols": "SteamNetworking",
    "ServerVisibility": "0",
    "WebDashboardEnabled": "false",
    "IgnoreEOSSanctions": "true",
    "EnemySpawnMode": "true",
    "ZombieMove": "2",
    "ZombieMoveNight": "3",
    "MaxSpawnedZombies": "64",
    "EnemyDifficulty": "1",
    "DayNightLength": "40",
    "DayLightLength": "12",
    "BuildCreate": "false",
}
for k, v in repls.items():
    src = re.sub(rf'name="{k}"\s*value="[^"]*"', f'name="{k}" value="{v}"', src)
Path("$TMPCFG").write_text(src, encoding="utf-8")
print(f"Config → $TMPCFG")
for line in src.splitlines():
    if any(x in line for x in (
        "GameWorld", "GameName", "WorldGen", "EnemySpawn", "ZombieMove",
        "MaxSpawnedZombies", "MaxPlayer",
    )):
        print(" ", line.strip())
PY

LOG="$USERDATA/server_prefab_${WORLD_NAME}_${WORLD_GEN_SIZE}_$(date +%Y-%m-%d__%H-%M-%S).txt"
echo "$LOG" >"$USERDATA/dedicated.logpath"
echo "Log: $LOG"
echo "Note: first RWG boot generates the 4k world (can take several minutes)."

cd "$DS_DIR"
nohup ./7DaysToDieServer.x86_64 \
  -logfile "$LOG" \
  -quit -batchmode -nographics -dedicated \
  -configfile="$TMPCFG" \
  >"$USERDATA/server_stdout_prefab.txt" 2>&1 &
echo $! >"$USERDATA/dedicated.pid"
echo "started pid=$(cat "$USERDATA/dedicated.pid")"

# RWG gen can take a while; allow up to ~10 min
ready=0
for i in $(seq 1 300); do
  if grep -q "StartGame done" "$LOG" 2>/dev/null; then
    echo "Server ready ($i * 2s)"
    grep -En "GameWorld|GameName|WorldGen|EnemySpawnMode|StartGame done|createWorld|Generating|RWG" "$LOG" | head -40
    ready=1
    break
  fi
  if ! kill -0 "$(cat "$USERDATA/dedicated.pid")" 2>/dev/null; then
    echo "ERROR: server exited early" >&2
    tail -60 "$LOG" || true
    exit 1
  fi
  # progress crumbs during long RWG gen
  if (( i % 15 == 0 )); then
    echo "… still waiting (${i}*2s); last log lines:"
    tail -3 "$LOG" 2>/dev/null || true
  fi
  sleep 2
done
if [[ "$ready" != "1" ]]; then
  echo "ERROR: timeout waiting for StartGame" >&2
  tail -60 "$LOG" || true
  exit 1
fi
ss -uln | grep -E '2690[0-2]' || true
echo "OK dedicated up: world=$WORLD_NAME size=$WORLD_GEN_SIZE seed=$WORLD_GEN_SEED"
echo "LiteNet join port typically 26902. Stop: kill \$(cat $USERDATA/dedicated.pid)"
