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
# WORLD_NAME lands in rm -rf targets and generated configs: restrict it to a
# single plain directory name so it cannot traverse or break quoting.
case "$WORLD_NAME" in
  ""|*[!A-Za-z0-9._-]*|[!A-Za-z0-9]*)
    echo "ERROR: RE_WORLD_NAME must be a plain directory name ([A-Za-z0-9._-], leading alnum; got: $WORLD_NAME)" >&2
    exit 1
    ;;
esac
WAIT_SEC="${RE_SERVER_WAIT:-180}"
SOAK_SEC="${RE_SERVER_SOAK:-35}"
for pair in "RE_SERVER_WAIT:$WAIT_SEC" "RE_SERVER_SOAK:$SOAK_SEC"; do
  v="${pair#*:}"
  case "$v" in
    ""|*[!0-9]*)
      echo "ERROR: ${pair%%:*} must be a non-negative integer (got: $v)" >&2
      exit 1
      ;;
  esac
done
SCRATCH_OUT="${RE_SCRATCH:-}"
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
if [[ ! -f "$CONFIG" ]]; then
  echo "ERROR: missing $CONFIG" >&2
  exit 1
fi

echo "=== RealEarth dedicated height test ==="
echo "Server:   $DS_DIR"
echo "UserData: $USERDATA"
echo "World:    $WORLD_NAME"
echo "Wait:     ${WAIT_SEC}s (no pause when empty, dedicated always simulates)"

# Kill previous test instance by /proc exe path (pgrep -x truncates long names).
# Match only servers under THIS install dir so unrelated 7DTD servers on a
# shared host are never signalled.
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  [[ -L "$d/exe" ]] || continue
  exe=$(readlink "$d/exe" 2>/dev/null || true)
  case "$exe" in "$DS_DIR"/*7DaysToDieServer.x86_64) kill "$pid" 2>/dev/null || true ;; esac
done
sleep 2

# Patch both client + dedicated Assembly-CSharp (Everest-scale YDim)
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
  # Pack selection: RE_SCENARIO_PACK=everest forces the Everest height_test
  # pack (matches the sibling 7dtd-loadgen convention); default prefers the
  # staged H500 pack, falling back to height_test when it is absent.
  local pack="$ROOT/data/samples/height_test_500"
  if [[ "${RE_SCENARIO_PACK:-}" == "everest" ]]; then
    pack="$ROOT/data/samples/height_test"
  fi
  if [[ ! -d "$pack/tiles" ]]; then
    pack="$ROOT/data/samples/height_test"
  fi
  if [[ -d "$pack/tiles" ]]; then
    rm -rf "$dest/Data/tiles"
    mkdir -p "$dest/Data/tiles"
    # pack layout is pack/tiles/*.rte, so TilePackPath=Data/tiles resolves Data/tiles/tiles/
    mkdir -p "$dest/Data/tiles/tiles"
    cp -a "$pack/tiles/." "$dest/Data/tiles/tiles/"
    for n in earth.manifest.json height_test.json preview_elev_m.png; do
      [[ -f "$pack/$n" ]] && cp -f "$pack/$n" "$dest/Data/tiles/"
    done
  fi
  # Prefer multiplayer template (SharedFixed + stream bubbles), fall back to default;
  # StreamRadiusTiles?=/UnloadRadiusTiles?= keep template values when present.
  PYTHONPATH="$ROOT/tools" python3 -m realearth.mod_config write "$dest" "$ROOT" \
    --sync-manifest --sync-bbox --height-test-meta \
    MapMode=Streamed \
    SingleWorldSession=true \
    EnableEngineHeightMod=true \
    EngineMaxGameY=29000 \
    EngineHeightOneToOne=true \
    "EngineHeightPreferVanillaCeiling=false" \
    TilePackPath=Data/tiles \
    WorldWidth=512 \
    WorldHeight=512 \
    TileSize=512 \
    LocalWindowSize=512 \
    EnableLongitudeWrap=false \
    DebugRevealFullMap=false \
    MultiplayerOriginMode=SharedFixed \
    "StreamRadiusTiles?=3" \
    "UnloadRadiusTiles?=5"
}

install_mod_to "$GAME_DIR"
install_mod_to "$DS_DIR"

# Ensure Harmony on dedicated
if [[ ! -d "$DS_DIR/Mods/0_TFP_Harmony" && -d "$GAME_DIR/Mods/0_TFP_Harmony" ]]; then
  cp -a "$GAME_DIR/Mods/0_TFP_Harmony" "$DS_DIR/Mods/"
  echo "Copied 0_TFP_Harmony → dedicated Mods/"
fi

# Generate H500 world if missing.
# Generation always emits worlds/RealEarth_H500 (height-test-map --peak-game-y 500);
# a RE_WORLD_NAME other than that can never be produced here, so fail fast instead of
# booting into a guaranteed GameWorld-not-found crash after the full WAIT window.
GENERATED_NAME="RealEarth_H500"
if [[ "$WORLD_NAME" != "$GENERATED_NAME" && ! -d "$ROOT/worlds/$WORLD_NAME" ]]; then
  echo "ERROR: RE_WORLD_NAME=$WORLD_NAME but no worlds/$WORLD_NAME exists and this" >&2
  echo "script can only generate $GENERATED_NAME. Pre-bake the world or use the default." >&2
  exit 1
fi
if [[ ! -d "$ROOT/worlds/$WORLD_NAME" ]]; then
  echo "Generating $WORLD_NAME..."
  (cd "$ROOT/tools" && uv run --locked python -m realearth.cli height-test-map --repo "$ROOT" --peak-game-y 500 --pack-size 512 --size 2048)
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

# Fresh save for clean load: move old saves into a trash window instead of
# deleting outright so a pointed-at-real-userdata run cannot destroy play
# progress irrecoverably. Trash older than RE_SAVE_TRASH_DAYS (default 7) is
# pruned on each run.
SAVE_TRASH_DAYS="${RE_SAVE_TRASH_DAYS:-7}"
TRASH="$USERDATA/Saves_trash"
mkdir -p "$TRASH"
# UTC stamp like the log name below: a fall-back DST hour would repeat a local
# stamp and mv would nest this trash entry inside the earlier one.
STAMP="$(date -u +%Y-%m-%d__%H-%M-%S)"
for sv in "$USERDATA/Saves/HeightTest500" "$USERDATA/Saves/$WORLD_NAME"; do
  if [[ -d "$sv" ]]; then
    mv "$sv" "$TRASH/${STAMP}__$(basename "$sv")"
  fi
done
find "$TRASH" -mindepth 1 -maxdepth 1 -mtime "+$SAVE_TRASH_DAYS" -exec rm -rf {} + 2>/dev/null || true

# Point serverconfig GameWorld + raise max players for 1000+ simulated-client load
MAX_PLAYERS="${RE_SERVER_MAX_PLAYERS:-1024}"
case "$MAX_PLAYERS" in
  ""|*[!0-9]*|0)
    echo "ERROR: RE_SERVER_MAX_PLAYERS must be a positive integer (got: $MAX_PLAYERS)" >&2
    exit 1
    ;;
esac
TMPCFG="$USERDATA/serverconfig_height_test.xml"
# Free all slots for load probes (no reserved/admin holds); max players default
# 1024 for 1000+ simulated clients.
PYTHONPATH="$ROOT/tools" python3 -m realearth.server_config \
  "$CONFIG" "$TMPCFG" --userdata "$USERDATA" \
  "GameWorld=$WORLD_NAME" \
  "ServerMaxPlayerCount=$MAX_PLAYERS" \
  ServerReservedSlots=0 \
  ServerAdminSlots=0

LOG="$USERDATA/server_test_$(date -u +%Y-%m-%d__%H-%M-%S)_$$.txt"
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

# The dedicated server never pauses when empty; make sure it cannot outlive this
# script if a failure or interrupt fires before the normal teardown below.
cleanup_server() {
  if kill -0 "$SPID" 2>/dev/null; then
    kill "$SPID" 2>/dev/null || true
    sleep 2
    kill -9 "$SPID" 2>/dev/null || true
  fi
}
trap cleanup_server EXIT INT TERM

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
      # "YDim expand active" is logged only when ChunkBlockYDim > 256, so any
      # RE_YDIM value passes (the old literal 16384 match broke --ydim overrides).
      if grep -Eq "RealEarth YDim expand active" "$LOG" 2>/dev/null; then
        if (( ok == 0 )); then
          ok=1
          loaded_at=$SECONDS
          echo "OK: world loaded with expanded YDim, soaking ${SOAK_SEC}s for late crashes..."
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
grep -En "RealEarth|YDim expand active|YDim|maxGameY|mpOrigin|SharedFixed|createWorld|World\.Load|Crash|Exception|EXC |SetHalf|UnsafeChunk" "$LOG" 2>/dev/null | head -100 || true
echo "======== last 40 log lines ========"
tail -40 "$LOG" 2>/dev/null || true

# Archive evidence
if [[ -n "$SCRATCH_OUT" && -d "$SCRATCH_OUT" && -f "$LOG" ]]; then
  cp -f "$LOG" "$SCRATCH_OUT/dedicated_height_test.log"
  cp -f "$LOG" "$SCRATCH_OUT/mp_dedicated.log" 2>/dev/null || true
  echo "Copied log → $SCRATCH_OUT/dedicated_height_test.log"
fi

# Stop server after test (dedicated does not pause when empty; we still tear down CI runs)
cleanup_server
trap - EXIT INT TERM

if (( ok == 1 )); then
  # Final gate checks
  # Expanded engine marker (any YDim > 256; RE_YDIM may legally differ from 16384)
  if ! grep -Eq "RealEarth YDim expand active" "$LOG"; then
    echo "FAIL: missing YDim-expand-active marker"
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
