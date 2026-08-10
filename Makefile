# RealEarth — top-level Makefile
# Run `make` or `make help` for targets.

.DEFAULT_GOAL := help
.PHONY: help help-all \
	setup tools-sync \
	test test-fast test-height test-python test-mp \
	build build-mod dll \
	install install-full install-baked install-streamed install-height install-height-500 \
	height-test height-map height-map-500 height-map-install height-map-500-install \
	engine-audit engine-expand engine-expand-dry engine-restore dedicated-height-test \
	demo bake bake-height package \
	viewer serve \
	info check clean clean-build

# ---------------------------------------------------------------------------
# Paths / knobs (override on the command line: make install GAME_DIR=...)
# ---------------------------------------------------------------------------
ROOT          := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
TOOLS         := $(ROOT)/tools
SCRIPTS       := $(ROOT)/scripts
SOURCE        := $(ROOT)/Source/RealEarth
CSPROJ        := $(SOURCE)/RealEarth.csproj
DLL_OUT       := $(SOURCE)/bin/Release/RealEarth.dll

GAME_DIR      ?= $(HOME)/.local/share/Steam/steamapps/common/7 Days To Die
export SEVENDTD_GAME_DIR := $(GAME_DIR)

# Prefer a local SDK if present (cache, goal scratch, or ~/.dotnet)
DOTNET_ROOT   ?= $(firstword \
	$(wildcard $(HOME)/.cache/dotnet-sdk) \
	$(wildcard /tmp/grok-goal-*/implementer/dotnet) \
	$(wildcard $(HOME)/.dotnet) \
	)
ifneq ($(DOTNET_ROOT),)
  export DOTNET_ROOT
  export PATH := $(DOTNET_ROOT):$(PATH)
endif

MAP_MODE      ?= Streamed
export MAP_MODE
WORLD_SIZE    ?= 2048
PACK_DEMO     := $(ROOT)/data/samples/demo_region
PACK_HEIGHT   := $(ROOT)/data/samples/height_test
WORLD_HEIGHT  := $(ROOT)/worlds/RealEarth_HeightTest

# uv-run tools CLI from tools/
UV            := uv
REEARTH       := cd $(TOOLS) && $(UV) run python -m realearth.cli
PYTEST        := cd $(TOOLS) && $(UV) run --with pytest python -m pytest

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help:
	@echo "RealEarth — common targets"
	@echo ""
	@echo "  Setup"
	@echo "    make setup              Sync Python tools (uv) + check game dir"
	@echo ""
	@echo "  Build / install (Steam Proton client)"
	@echo "    make build              Build RealEarth.dll"
	@echo "    make install            Build + install mod+worlds (MAP_MODE=$(MAP_MODE))"
	@echo "    make install-full       RealEarth YDim expand + install (full product)"
	@echo "    make install-baked      Same with MAP_MODE=Baked"
	@echo "    make install-streamed   Same with MAP_MODE=Streamed"
	@echo "    make install-height     Height-test map + install (Everest DEM)"
	@echo "    make install-height-500 Staged 500-block peak map + install (fast test)"
	@echo "    make package            dist/RealEarth (+ Tools/ YDim expand)"
	@echo ""
	@echo "  Height mod"
	@echo "    make height-test        Offline height-mod smoke (Everest + fly room)"
	@echo "    make height-map         Generate Everest height-test pack + baked world"
	@echo "    make height-map-500     Generate staged peak gameY=500 pack + world"
	@echo "    make height-map-install Generate Everest + install for Proton New Game"
	@echo "    make engine-audit       Print Assembly-CSharp YDim / cMaxHeight"
	@echo "    make engine-expand      RealEarth YDim expand (part of this mod)"
	@echo "    make engine-expand-dry  Preview IL patches without writing"
	@echo "    make engine-restore     Restore stock Assembly-CSharp from backup"
	@echo ""
	@echo "  Data / worlds"
	@echo "    make demo               Synthetic demo region pack"
	@echo "    make bake               Bake GeneratedWorld from demo pack"
	@echo "    make bake-height        Bake RealEarth_HeightTest only"
	@echo ""
	@echo "  Tests"
	@echo "    make test               Full Python test suite"
	@echo "    make test-height        Height mod + height-test map tests only"
	@echo "    make test-fast          Quick subset (coords, height, tiles)"
	@echo ""
	@echo "  Viewer"
	@echo "    make viewer             Export demo pack into viewer/data/demo"
	@echo "    make serve              Serve web map viewer (port 8765)"
	@echo ""
	@echo "  Misc"
	@echo "    make info               Paths + tool versions"
	@echo "    make check              setup + test-fast + build"
	@echo "    make clean              Remove Python caches / build artifacts"
	@echo ""
	@echo "Overrides: GAME_DIR=... MAP_MODE=Baked|Streamed WORLD_SIZE=2048 DOTNET_ROOT=..."
	@echo "Also:      make -C tools help"

help-all: help
	@$(MAKE) -C $(TOOLS) help

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
setup: tools-sync
	@test -d "$(GAME_DIR)/7DaysToDie_Data/Managed" \
		&& echo "OK game: $(GAME_DIR)" \
		|| echo "WARN: game Managed/ not found at $(GAME_DIR)"
	@command -v dotnet >/dev/null && dotnet --list-sdks | head -3 || echo "WARN: dotnet not on PATH (set DOTNET_ROOT=...)"
	@echo "OK tools ready"

tools-sync:
	@cd $(TOOLS) && $(UV) sync --extra dev
	@echo "OK uv sync (tools/)"

# ---------------------------------------------------------------------------
# Build / install
# ---------------------------------------------------------------------------
build build-mod dll:
	@test -f "$(CSPROJ)"
	@echo "Building $(CSPROJ) → Release"
	dotnet build "$(CSPROJ)" -c Release -p:GameDir="$(GAME_DIR)"
	@test -f "$(DLL_OUT)" && ls -la "$(DLL_OUT)"

install: build
	@echo "Installing (MAP_MODE=$(MAP_MODE)) → $(GAME_DIR)"
	MAP_MODE="$(MAP_MODE)" "$(SCRIPTS)/install_proton.sh"

# Full RealEarth: YDim expand (part of this mod) + mod DLL + worlds
install-full: engine-expand install
	@echo "OK install-full (YDim expand + RealEarth mod). Restart 7DTD."

install-baked:
	@$(MAKE) install MAP_MODE=Baked

install-streamed:
	@$(MAKE) install MAP_MODE=Streamed

install-height: height-map-install

package: build
	@chmod +x "$(SCRIPTS)/apply_engine_expand.sh" 2>/dev/null || true
	@GAME_DIR="$(GAME_DIR)" "$(SCRIPTS)/package_mod.sh" "$(ROOT)/dist/RealEarth"
	@echo "OK package → $(ROOT)/dist/RealEarth (includes Tools/ YDim expand)"

# ---------------------------------------------------------------------------
# Height mod
# ---------------------------------------------------------------------------
height-test:
	@$(REEARTH) height-mod-test

height-map:
	@$(REEARTH) height-test-map --repo "$(ROOT)" --size $(WORLD_SIZE) \
		--source terrarium --terrarium-zoom 12

height-map-500:
	@$(REEARTH) height-test-map --repo "$(ROOT)" --size $(WORLD_SIZE) \
		--peak-game-y 500 --pack-size 512

height-map-install:
	@$(REEARTH) height-test-map --repo "$(ROOT)" --size $(WORLD_SIZE) \
		--source terrarium --terrarium-zoom 12 --install

height-map-500-install:
	@$(REEARTH) height-test-map --repo "$(ROOT)" --size $(WORLD_SIZE) \
		--peak-game-y 500 --pack-size 512 --install

install-height-500: build height-map-500-install
	@chmod +x "$(SCRIPTS)/install_height_pack.sh"
	@"$(SCRIPTS)/install_height_pack.sh" h500
	@echo "OK RealEarth_H500. New Game -> RealEarth_H500 (peak gameY=500)"

install-height-pack-everest: build
	@chmod +x "$(SCRIPTS)/install_height_pack.sh"
	@"$(SCRIPTS)/install_height_pack.sh" everest

engine-audit:
	@$(REEARTH) engine-audit

# RealEarth YDim expand (part of this mod — not a third-party tool).
# Close the game first. Re-run after Steam verify/updates.
engine-expand:
	@chmod +x "$(SCRIPTS)/apply_engine_expand.sh" "$(SCRIPTS)/patch_engine_height.sh"
	@"$(SCRIPTS)/patch_engine_height.sh" --force
	@echo "Rebuilding RealEarth.dll..."
	@$(MAKE) build
	@echo "OK RealEarth YDim expand. Restart 7DTD. (Also: Mods/RealEarth/Tools/ after make package)"

engine-expand-dry:
	@chmod +x "$(SCRIPTS)/patch_engine_height.sh"
	@"$(SCRIPTS)/patch_engine_height.sh" --dry-run

engine-restore:
	@DLL="$(GAME_DIR)/7DaysToDie_Data/Managed/Assembly-CSharp.dll"; \
	BAK="$$DLL.re_stock_bak"; \
	if [[ ! -f "$$BAK" ]]; then echo "No backup at $$BAK"; exit 1; fi; \
	cp -a "$$BAK" "$$DLL"; \
	rm -f "$$DLL.re_height_expanded"; \
	echo "Restored stock: $$DLL"; \
	DS="$(HOME)/.local/share/Steam/steamapps/common/7 Days to Die Dedicated Server/7DaysToDieServer_Data/Managed/Assembly-CSharp.dll"; \
	if [[ -f "$$DS.re_stock_bak" ]]; then cp -a "$$DS.re_stock_bak" "$$DS"; rm -f "$$DS.re_height_expanded"; echo "Restored stock: $$DS"; fi; \
	$(MAKE) build

# Headless dedicated load test (Everest-scale YDim). Does not pause when empty.
# Installs SharedFixed multiplayer config from Config/realearth.mp.json.
# ServerMaxPlayerCount defaults to 1024 (RE_SERVER_MAX_PLAYERS overrides).
dedicated-height-test:
	@chmod +x "$(SCRIPTS)/run_dedicated_height_test.sh"
	@"$(SCRIPTS)/run_dedicated_height_test.sh"

# Unit multiplayer model + C# structure (LiteNet load bots live in sibling 7dtd-loadgen)
test-mp:
	@$(PYTEST) tests/test_multiplayer.py tests/test_host_fold.py tests/test_local_window.py \
		tests/test_mp_runtime_structure.py -q --tb=short

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
demo:
	@$(REEARTH) demo --out "$(PACK_DEMO)"
	@echo "OK demo pack → $(PACK_DEMO)"

bake:
	@$(REEARTH) bake-world --pack "$(PACK_DEMO)" --out "$(ROOT)/worlds/RealEarth" \
		--size 4096 --name RealEarth --generated
	@echo "OK world → $(ROOT)/worlds/RealEarth"

bake-height: height-map

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
test test-python:
	@$(PYTEST) -q --tb=short

test-height:
	@$(PYTEST) tests/test_height_mod_case.py tests/test_height_10k.py \
		tests/test_height_test_map.py tests/test_engine_constants.py \
		tests/test_engine_expand_rules.py tests/test_host_fold.py \
		tests/test_local_window.py tests/test_multiplayer.py \
		tests/test_mp_runtime_structure.py -q --tb=short
	@$(REEARTH) height-mod-test

test-fast:
	@$(PYTEST) tests/test_coords.py tests/test_tile_roundtrip.py \
		tests/test_height_mod_case.py tests/test_height_10k.py \
		tests/test_region.py tests/test_viewer_export.py \
		tests/test_proton_paths.py tests/test_elevation_terrarium.py \
		tests/test_multiplayer.py tests/test_host_fold.py tests/test_local_window.py \
		tests/test_mp_runtime_structure.py -q --tb=line

check: setup test-fast build
	@echo "OK check (setup + test-fast + build)"

# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------
viewer:
	@$(REEARTH) export-viewer --pack "$(PACK_DEMO)" --out "$(ROOT)/viewer/data/demo"
	@echo "OK viewer data → $(ROOT)/viewer/data/demo"

serve:
	@$(REEARTH) serve --port 8765

# ---------------------------------------------------------------------------
# Info / clean
# ---------------------------------------------------------------------------
info:
	@echo "ROOT       = $(ROOT)"
	@echo "GAME_DIR   = $(GAME_DIR)"
	@echo "DOTNET_ROOT= $(DOTNET_ROOT)"
	@echo "MAP_MODE   = $(MAP_MODE)"
	@echo "DLL_OUT    = $(DLL_OUT)"
	@echo "PACK_DEMO  = $(PACK_DEMO)"
	@echo "PACK_HEIGHT= $(PACK_HEIGHT)"
	@command -v dotnet >/dev/null && echo -n "dotnet     = " && dotnet --version || echo "dotnet     = (missing)"
	@command -v uv >/dev/null && echo -n "uv         = " && uv --version || echo "uv         = (missing)"
	@$(REEARTH) info 2>/dev/null || true

clean: clean-build
	@find $(TOOLS) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find $(TOOLS) -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@rm -rf $(TOOLS)/.ruff_cache 2>/dev/null || true
	@echo "OK cleaned Python caches"

clean-build:
	@rm -rf $(SOURCE)/bin $(SOURCE)/obj
	@echo "OK cleaned C# bin/obj"
