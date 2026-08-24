# RealEarth Python tools (run from tools/ or: make -C tools <target>)

.DEFAULT_GOAL := help
.PHONY: help setup sync test test-height height-test engine-audit \
	demo height-map height-map-install bake sample-chunk serve lint info clean

ROOT   := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
UV     := uv
REEARTH := $(UV) run python -m realearth.cli
# --extra dev keeps pytest on uv.lock (a bare --with pytest would float).
PYTEST := $(UV) run --extra dev python -m pytest

help:
	@echo "RealEarth tools/ — Python pipeline"
	@echo ""
	@echo "  make setup | sync       uv sync --extra dev"
	@echo "  make test               Full pytest suite"
	@echo "  make test-height        Height mod + map tests"
	@echo "  make height-test        CLI height-mod smoke case"
	@echo "  make engine-audit       Probe 7DTD YDim constants"
	@echo "  make demo               Synthetic demo region"
	@echo "  make height-map         Everest height-test pack+world"
	@echo "  make height-map-install Generate + Proton install"
	@echo "  make bake               Bake worlds/RealEarth from demo pack"
	@echo "  make sample-chunk       Sample Streamed chunk (demo pack)"
	@echo "  make serve              Web viewer on :8765"
	@echo "  make lint               ruff check (realearth, tests, scripts)"
	@echo "  make info               realearth info"
	@echo "  make clean              pycache / pytest cache"
	@echo ""
	@echo "Repo root also has: make -C .. help"

setup sync:
	$(UV) sync --extra dev

test:
	$(PYTEST) -q --tb=short

test-height:
	$(PYTEST) tests/test_height_mod_case.py tests/test_height_10k.py \
		tests/test_height_test_map.py tests/test_engine_constants.py -q --tb=short
	$(REEARTH) height-mod-test

height-test:
	$(REEARTH) height-mod-test

engine-audit:
	$(REEARTH) engine-audit

demo:
	$(REEARTH) demo --out $(ROOT)/data/samples/demo_region

height-map:
	$(REEARTH) height-test-map --repo $(ROOT) --size 2048

height-map-install:
	$(REEARTH) height-test-map --repo $(ROOT) --size 2048 --install

bake:
	$(REEARTH) bake-world --pack $(ROOT)/data/samples/demo_region \
		--out $(ROOT)/worlds/RealEarth --size 4096 --name RealEarth --generated

sample-chunk:
	$(REEARTH) sample-chunk --pack $(ROOT)/data/samples/demo_region --x 100 --z 100

serve:
	$(REEARTH) serve --port 8765 --root $(ROOT)/viewer

lint:
	$(UV) run --extra dev ruff check realearth tests ../scripts/coverage_badge.py

info:
	$(REEARTH) info

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .ruff_cache
	@echo "OK tools clean"
