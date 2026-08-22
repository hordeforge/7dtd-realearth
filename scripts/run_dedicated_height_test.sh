#!/usr/bin/env bash
# Headless dedicated-server load test for RealEarth engine height expand.
# Dedicated servers do not pause when empty (unlike client listen-host).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GAME_DIR="${SEVENDTD_GAME_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days To Die}"
DS_DIR="${SEVENDTD_SERVER_DIR:-$HOME/.local/share/Steam/steamapps/common/7 Days to Die Dedicated Server}"
USERDATA="${RE_DEDICATED_USERDATA:-$HOME/.cache/realearth-dedicated}"
CONFIG="$ROOT/scripts/serverconfig_height_test.xml"
WORLD_NAME="${RE_WORLD_NAME:-RealEarth_H500}"
WAIT_SEC="${RE_SERVER_WAIT:-180}"
SOAK_SEC="${RE_SERVER_SOAK:-35}"
SCRATCH_OUT="${RE_SCRATCH:-}"
DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.cache/dotnet-sdk}"
export PATH="${DOTNET_ROOT}:${PATH}"

if [[ ! -x "$DS_DIR/7DaysToDieServer.x86_64" ]]; then
  echo "ERROR: dedicated server not found: $DS_DIR" >&2
  exit 1
fi
if [[ ! -f "$CONFIG" ]]; then
  echo "ERROR: missing $CONFIG" >&2
  exit 1
fi

echo "=== RealEarth dedicated height test ==="
echo "Server:   $DS_DIR"
echo "UserData: $USERDATA"
echo "World:    $WORLD_NAME"
echo "Wait:     ${WAIT_SEC}s (no pause when empty — dedicated always simulates)"

# Kill previous test instance if any (exact name; avoid pkill -f self-match)
pgrep -x '7DaysToDieServer.x86_64' 2>/dev/null | xargs -r kill 2>/dev/null || true
sleep 1

# Patch both client + dedicated Assembly-CSharp (Everest-scale YDim)
export DOTNET_ROOT
export SEVENDTD_GAME_DIR="$GAME_DIR"
export SEVENDTD_SERVER_DIR="$DS_DIR"
chmod +x "$ROOT/scripts/patch_engine_height.sh"
"$ROOT/scripts/patch_engine_height.sh" --force

# Build + install mod to client and dedicated
dotnet build "$ROOT/Source/RealEarth/RealEarth.csproj" -c Release -p:GameDir="$GAME_DIR" -v q
DLL="$ROOT/Source/RealEarth/bin/Release/RealEarth.dll"
test -f "$DLL"

install_mod_to() {
  local target="$1"
  local dest="$target/Mods/RealEarth"
  mkdir -p "$dest/Config" "$dest/Data/tiles"
  cp -f "$ROOT/ModInfo.xml" "$dest/"
  cp -f "$DLL" "$dest/"
  # Prefer staged H500 pack if present, else height_test
  local pack="$ROOT/data/samples/height_test_500"
  if [[ ! -d "$pack/tiles" ]]; then
    pack="$ROOT/data/samples/height_test"
  fi
  if [[ -d "$pack/tiles" ]]; then
    rm -rf "$dest/Data/tiles"
    mkdir -p "$dest/Data"
    cp -a "$pack/." "$dest/Data/tiles/" 2>/dev/null || true
    # pack layout is pack/tiles/*.rte — install_proton copies pack/tiles into Data/tiles
    if [[ -d "$pack/tiles" ]]; then
      rm -rf "$dest/Data/tiles"
      mkdir -p "$dest/Data/tiles"
      cp -a "$pack/tiles/." "$dest/Data/tiles/tiles/" 2>/dev/null || cp -a "$pack/tiles" "$dest/Data/tiles/"
      for n in earth.manifest.json height_test.json preview_elev_m.png; do
        [[ -f "$pack/$n" ]] && cp -f "$pack/$n" "$dest/Data/tiles/"
      done
    fi
  fi
  python3 - <<PY
import json
from pathlib import Path
cfg_path = Path("$dest/Config/realearth.json")
cfg_path.parent.mkdir(parents=True, exist_ok=True)
root = Path("$ROOT")
# Prefer multiplayer template (SharedFixed + stream bubbles), fall back to default
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
    "EngineHeightOneToOne": True,
    "EngineHeightPreferVanillaCeiling": False,
    "EngineHeightForceExpandedCompress": True,
    "TilePackPath": "Data/tiles",
    "WorldWidth": 512,
    "WorldHeight": 512,
    "TileSize": 512,
    "LocalWindowSize": 512,
    "EnableLongitudeWrap": False,
    "DebugRevealFullMap": False,
    "MultiplayerOriginMode": "SharedFixed",
    "StreamRadiusTiles": int(cfg.get("StreamRadiusTiles") or 3),
    "UnloadRadiusTiles": int(cfg.get("UnloadRadiusTiles") or 5),
})
man = Path("$dest/Data/tiles/earth.manifest.json")
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
ht = Path("$dest/Data/tiles/height_test.json")
if ht.is_file():
    meta = json.loads(ht.read_text(encoding="utf-8"))
    if meta.get("summit_lon") is not None:
        cfg["SpawnLongitude"] = float(meta["summit_lon"])
        cfg["SpawnLatitude"] = float(meta["summit_lat"])
        cfg["DefaultSpawnLon"] = cfg["SpawnLongitude"]
        cfg["DefaultSpawnLat"] = cfg["SpawnLatitude"]
    # staged maps may set engine_max_game_y; Everest-scale still allows 11000 ceiling
    if int(meta.get("engine_max_game_y") or 0) > 500:
        cfg["EngineMaxGameY"] = int(meta["engine_max_game_y"])
cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print(f"Installed mod → $dest  EngineMaxGameY={cfg['EngineMaxGameY']}")
PY
}

install_mod_to "$GAME_DIR"
install_mod_to "$DS_DIR"

# Ensure Harmony on dedicated
if [[ ! -d "$DS_DIR/Mods/0_TFP_Harmony" && -d "$GAME_DIR/Mods/0_TFP_Harmony" ]]; then
  cp -a "$GAME_DIR/Mods/0_TFP_Harmony" "$DS_DIR/Mods/"
  echo "Copied 0_TFP_Harmony → dedicated Mods/"
fi

# Generate H500 world if missing
if [[ ! -d "$ROOT/worlds/$WORLD_NAME" ]]; then
  echo "Generating $WORLD_NAME..."
  (cd "$ROOT/tools" && uv run python -m realearth.cli height-test-map --repo "$ROOT" --peak-game-y 500 --pack-size 512 --size 2048)
fi

# Install world into dedicated userdata GeneratedWorlds
mkdir -p "$USERDATA/GeneratedWorlds" "$USERDATA/Saves"
if [[ -d "$ROOT/worlds/$WORLD_NAME" ]]; then
  rm -rf "$USERDATA/GeneratedWorlds/$WORLD_NAME"
  cp -a "$ROOT/worlds/$WORLD_NAME" "$USERDATA/GeneratedWorlds/$WORLD_NAME"
  echo "World → $USERDATA/GeneratedWorlds/$WORLD_NAME"
fi
# Also native Linux GeneratedWorlds (some server builds look there)
if [[ -d "$HOME/.local/share/7DaysToDie/GeneratedWorlds" ]]; then
  rm -rf "$HOME/.local/share/7DaysToDie/GeneratedWorlds/$WORLD_NAME"
  cp -a "$ROOT/worlds/$WORLD_NAME" "$HOME/.local/share/7DaysToDie/GeneratedWorlds/$WORLD_NAME"
fi

# Fresh save for clean load
rm -rf "$USERDATA/Saves/HeightTest500" "$USERDATA/Saves/$WORLD_NAME" 2>/dev/null || true

# Point serverconfig GameWorld + raise max players for 1000+ simulated-client load
MAX_PLAYERS="${RE_SERVER_MAX_PLAYERS:-1024}"
TMPCFG="$USERDATA/serverconfig_height_test.xml"
python3 - <<PY
from pathlib import Path
import re
src = Path("$CONFIG").read_text(encoding="utf-8")
# inject UserDataFolder
if "UserDataFolder" not in src or "absolute_path" in src:
    src = src.replace(
        '<!-- <property name="UserDataFolder" value="absolute_path"/> -->',
        f'<property name="UserDataFolder" value="{Path("$USERDATA").resolve()}"/>',
    )
    if 'name="UserDataFolder"' not in src:
        src = src.replace(
            "<ServerSettings>",
            f'<ServerSettings>\n\t<property name="UserDataFolder" value="{Path("$USERDATA").resolve()}"/>',
        )
src = re.sub(
    r'name="GameWorld"\s*value="[^"]*"',
    f'name="GameWorld" value="$WORLD_NAME"',
    src,
)
# Always apply max-player override (default 1024 for 1000+ simulated clients)
src = re.sub(
    r'name="ServerMaxPlayerCount"\s*value="[^"]*"',
    f'name="ServerMaxPlayerCount" value="$MAX_PLAYERS"',
    src,
)
# Free all slots for load probes (no reserved/admin holds)
src = re.sub(
    r'name="ServerReservedSlots"\s*value="[^"]*"',
    'name="ServerReservedSlots" value="0"',
    src,
)
src = re.sub(
    r'name="ServerAdminSlots"\s*value="[^"]*"',
    'name="ServerAdminSlots" value="0"',
    src,
)
Path("$TMPCFG").write_text(src, encoding="utf-8")
print(f"Config → $TMPCFG  ServerMaxPlayerCount=$MAX_PLAYERS")
PY

LOG="$USERDATA/server_test_$(date +%Y-%m-%d__%H-%M-%S).txt"
mkdir -p "$USERDATA"
cd "$DS_DIR"
export LD_LIBRARY_PATH="."

echo "Starting dedicated server (log: $LOG)..."
./7DaysToDieServer.x86_64 \
  -logfile "$LOG" \
  -quit -batchmode -nographics -dedicated \
  -configfile="$TMPCFG" \
  >"$USERDATA/server_stdout.txt" 2>&1 &
SPID=$!
echo "PID=$SPID"

# Poll for success / crash
deadline=$((SECONDS + WAIT_SEC))
ok=0
loaded_at=0
while (( SECONDS < deadline )); do
  if ! kill -0 "$SPID" 2>/dev/null; then
    echo "Server process exited early."
    break
  fi
  if [[ -f "$LOG" ]]; then
    if grep -Eq "Crash!!!|UnsafeChunkData|IndexOutOfRangeException|TypeInitializationException|Exception in thread GenerateChunks" "$LOG" 2>/dev/null; then
      echo "FAIL: crash/exception detected in log"
      ok=0
      break
    fi
    if grep -Eq "createWorld\(\) done|StartGame done" "$LOG" 2>/dev/null \
      && grep -Eq "World\.Load:|createWorld:" "$LOG" 2>/dev/null; then
      if grep -Eq "ENGINE EXPANDED|engineYDim=16384|YDim=16384" "$LOG" 2>/dev/null; then
        if (( ok == 0 )); then
          ok=1
          loaded_at=$SECONDS
          echo "OK: world loaded with expanded YDim — soaking ${SOAK_SEC}s for late crashes..."
          # Optional: capacity bots live in sibling 7dtd-loadgen (not this tree)
          if [[ "${LOADGEN_RUN_CLIENTS:-0}" == "1" ]]; then
            LT="${RE_LOADTEST_ROOT:-$ROOT/../7dtd-loadgen}"
            if [[ -x "$LT/scripts/run_loadgen.sh" ]] || [[ -f "$LT/scripts/run_loadgen.sh" ]]; then
              echo "=== Running loadtest bots from $LT ==="
              LOADGEN_HOST="${LOADGEN_HOST:-127.0.0.1}" \
              LOADGEN_PORT="${LOADGEN_PORT:-26900}" \
              RE_SCRATCH="${SCRATCH_OUT:-}" \
                bash "$LT/scripts/run_loadgen.sh" \
                && echo "OK: loadtest bots" \
                || echo "NOTE: loadtest bots did not pass (see $LT logs)"
            else
              echo "NOTE: LOADGEN_RUN_CLIENTS=1 but 7dtd-loadgen not found at $LT"
            fi
          fi
        fi
        # Soak window: keep running and re-check for crash lines
        if (( SECONDS - loaded_at >= SOAK_SEC )); then
          if grep -Eq "Crash!!!|UnsafeChunkData|IndexOutOfRangeException|Exception in thread GenerateChunks" "$LOG" 2>/dev/null; then
            echo "FAIL: crash during soak"
            ok=0
          else
            echo "OK: soak complete without crash"
          fi
          break
        fi
      fi
    fi
  fi
  sleep 2
done

echo "======== RealEarth lines ========"
grep -En "RealEarth|ENGINE EXPANDED|YDim|maxGameY|mpOrigin|SharedFixed|createWorld|World\.Load|Crash|Exception|EXC |SetHalf|UnsafeChunk" "$LOG" 2>/dev/null | head -100 || true
echo "======== last 40 log lines ========"
tail -40 "$LOG" 2>/dev/null || true

# Archive evidence
if [[ -n "$SCRATCH_OUT" && -d "$SCRATCH_OUT" && -f "$LOG" ]]; then
  cp -f "$LOG" "$SCRATCH_OUT/dedicated_height_test.log"
  cp -f "$LOG" "$SCRATCH_OUT/mp_dedicated.log" 2>/dev/null || true
  echo "Copied log → $SCRATCH_OUT/dedicated_height_test.log"
fi

# Stop server after test (dedicated does not pause when empty; we still tear down CI runs)
if kill -0 "$SPID" 2>/dev/null; then
  kill "$SPID" 2>/dev/null || true
  sleep 2
  kill -9 "$SPID" 2>/dev/null || true
fi

if (( ok == 1 )); then
  # Final gate checks
  if ! grep -Eq "YDim=16384|engineYDim=16384" "$LOG"; then
    echo "FAIL: missing Everest-scale YDim marker"
    exit 1
  fi
  if ! grep -Eq "createWorld\(\) done|StartGame done" "$LOG"; then
    echo "FAIL: missing createWorld/StartGame done"
    exit 1
  fi
  if ! grep -Eq "RealEarth_H500|$WORLD_NAME" "$LOG"; then
    echo "FAIL: missing world name"
    exit 1
  fi
  if grep -Eq "Crash!!!|UnsafeChunkData|Index was outside the bounds of the array" "$LOG"; then
    echo "FAIL: crash markers present"
    exit 1
  fi
  if grep -Eq "Spawn sample pack-center|sessionPeak=|Height inject" "$LOG"; then
    echo "OK: height sample/inject lines present"
  fi
  if grep -Eq "mpOrigin=SharedFixed|MultiplayerOriginMode.*SharedFixed" "$LOG"; then
    echo "OK: SharedFixed multiplayer origin active"
  elif grep -Eq "RealEarth init OK" "$LOG"; then
    # Confirm installed config on disk
    if grep -Eq '"MultiplayerOriginMode"[[:space:]]*:[[:space:]]*"SharedFixed"' "$DS_DIR/Mods/RealEarth/Config/realearth.json" 2>/dev/null; then
      echo "OK: SharedFixed in dedicated realearth.json"
    else
      echo "NOTE: SharedFixed not confirmed in log (check Config)"
    fi
  fi
  if grep -Eq "gameY=5[0-9]{2}|sessionPeak=5[0-9]{2}|maxH=5[0-9]{2}" "$LOG"; then
    echo "OK: near-500 height band observed (H500 peak)"
  elif grep -Eq "gameY=8[0-9]{3}|sessionPeak=8[0-9]{3}|maxH=8[0-9]{3}" "$LOG"; then
    echo "OK: Everest-scale height band observed"
  else
    echo "NOTE: peak height band not in log (load still clean)"
  fi
  if grep -Eq "Patch failed ITerrainGenerator|Patch failed IChunkProvider" "$LOG"; then
    echo "NOTE: still saw interface patch noise (should be gone after concrete-only patch)"
  fi
  echo
  echo "PASS: dedicated server loaded + soaked cleanly (SharedFixed MP path)."
  echo "Log: $LOG"
  exit 0
fi

echo
echo "FAIL or timeout after ${WAIT_SEC}s. Inspect: $LOG"
exit 1
