#!/usr/bin/env bash
# Assemble a Mods/RealEarth folder ready to copy into the game.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/dist/RealEarth}"
GAME_DIR="${SEVENDTD_GAME_DIR:-${GameDir:-}}"

rm -rf "$OUT"
mkdir -p "$OUT/Config" "$OUT/Data" "$OUT"

cp "$ROOT/ModInfo.xml" "$OUT/"
cp "$ROOT/Config/realearth.json" "$OUT/Config/"
[[ -f "$ROOT/Config/nav_objects.xml" ]] && cp -f "$ROOT/Config/nav_objects.xml" "$OUT/Config/"
cp "$ROOT/ATTRIBUTION.md" "$OUT/" 2>/dev/null || true
# Ensure single-world defaults are present in packaged config
if command -v python3 >/dev/null; then
  python3 - <<'PY' "$OUT/Config/realearth.json"
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    cfg = json.load(f)
cfg.setdefault("MapMode", "Streamed")
cfg.setdefault("SingleWorldSession", True)
cfg.setdefault("LocalWindowSize", 1024)
cfg.setdefault("MultiplayerOriginMode", "SoloSlide")
cfg.setdefault("StreamRadiusTiles", 2)
cfg.setdefault("UnloadRadiusTiles", 4)
# StockSafe = fallback until Tools/apply_engine_expand runs (expand is part of RealEarth)
cfg["EngineHeightStockSafe"] = False
cfg.setdefault("DebugRevealFullMap", True)
cfg.setdefault("ShowCityNamesOnMap", True)
cfg.setdefault("CityMapDiscoverRadiusScale", 1.0)
cfg.setdefault("DebugMapRevealRadiusChunks", 128)
cfg.setdefault("EnableEngineHeightMod", True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print("packaged config (StockSafe fallback until YDim expand)")
PY
fi
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
  # Point config at packaged tiles
  if command -v python3 >/dev/null; then
    python3 - <<'PY' "$OUT/Config/realearth.json"
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    cfg = json.load(f)
cfg["TilePackPath"] = "Data/tiles"
# Demo pack is local-indexed region, not full Earth dimensions
cfg["WorldWidth"] = 1024
cfg["WorldHeight"] = 1024
cfg["EnableLongitudeWrap"] = False
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print("updated", path)
PY
  fi
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
    echo "WARNING: DLL not found"
  fi
else
  echo "NOTE: set SEVENDTD_GAME_DIR to build RealEarth.dll into the package."
  echo "      Heightmap export under Data/tiles/export_7dtd still works without the DLL."
fi

# Stock dashboard webui (WebMod auto-served by the game webserver)
if [[ -d "$ROOT/WebMod" ]]; then
  mkdir -p "$OUT/WebMod"
  cp -a "$ROOT/WebMod/." "$OUT/WebMod/"
  echo "Packaged WebMod/ (stock dashboard webui)"
else
  echo "NOTE: no WebMod/ build output — run make webmod-export + make webmod to include the dashboard webui."
fi

# RealEarth YDim expand tools (part of this mod)
mkdir -p "$OUT/Tools"
PATCHER_SRC="$ROOT/tools/engine_patcher/bin/Release"
if [[ ! -f "$PATCHER_SRC/EngineHeightPatcher.exe" && -n "${GAME_DIR:-}" ]]; then
  HARMONY="${GAME_DIR}/Mods/0_TFP_Harmony"
  if [[ -d "$HARMONY" ]] && command -v dotnet >/dev/null; then
    echo "Building RealEarth EngineHeightPatcher into package..."
    dotnet build "$ROOT/tools/engine_patcher/EngineHeightPatcher.csproj" -c Release \
      -p:HarmonyDir="$HARMONY" -v q || true
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
  echo "NOTE: EngineHeightPatcher not built — run make engine-expand from the repo after install."
fi

echo "Packaged → $OUT"
echo "Copy into: <7DaysToDie>/Mods/RealEarth/"
echo "Full RealEarth: run Tools/apply_engine_expand.sh (YDim expand is part of this mod)."
echo "See Docs/MODLET.md"