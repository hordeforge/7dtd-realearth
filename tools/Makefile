# RealEarth Python tools (run from tools/ or: make -C tools <target>)

.DEFAULT_GOAL := help
.PHONY: help setup sync test test-one test-height height-test engine-audit \
	demo height-map height-map-install bake sample-chunk serve lint info clean

ROOT   := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
UV     := uv
# --locked fails every target when pyproject.toml drifts from uv.lock, so a
# dependency change needs an explicit `uv lock` review instead of any make
# invocation silently re-resolving and rewriting the lockfile.
REEARTH := $(UV) run --locked python -m realearth.cli
# --extra dev keeps pytest on uv.lock (a bare --with pytest would float).
PYTEST := $(UV) run --locked --extra dev python -m pytest
# Same gate as the repo-root Makefile lint target (which CI also runs): every
# tool invocation stays on uv.lock, never a fresh resolution.
RUFF := $(UV) run --locked --extra dev ruff check realearth tests ../scripts
BLACK := $(UV) run --locked --extra dev black --check --config pyproject.toml realearth tests ../scripts
MYPY := $(UV) run --locked --extra dev mypy realearth ../scripts

help:
	@echo "RealEarth tools/: Python pipeline"
	@echo ""
	@echo "  make setup | sync       uv sync --locked --extra dev"
	@echo "  make test               Full pytest suite"
	@echo "  make test-one T=tests/test_coords.py   Single file (or -k expr)"
	@echo "  make test-height        Height mod + map tests"
	@echo "  make height-test        CLI height-mod smoke case"
	@echo "  make engine-audit       Probe 7DTD YDim constants"
	@echo "  make demo               Synthetic demo region"
	@echo "  make height-map         Everest height-test pack+world"
	@echo "  make height-map-install Generate + Proton install"
	@echo "  make bake               Bake worlds/RealEarth from demo pack"
	@echo "  make sample-chunk       Sample Streamed chunk (demo pack)"
	@echo "  make serve              Web viewer on :8765"
	@echo "  make lint               ruff + black (realearth, tests, ../scripts);"
	@echo "                          mypy strict over tools/pyproject [tool.mypy] files"
	@echo "  make info               realearth info"
	@echo "  make clean              pycache / pytest cache"
	@echo ""
	@echo "Repo root also has: make -C .. help"

setup sync:
	$(UV) sync --locked --extra dev

test:
	$(PYTEST) -q --tb=short

# Single test file / node / -k expression, e.g.:
#   make test-one T=tests/test_coords.py
#   make test-one T=tests/test_coords.py::test_lonlat_wrap
#   make test-one T=-kwrap
T ?=
test-one:
	@test -n "$(T)" || { echo "ERROR: pass T=<tests/file.py[::node] | -k expr>" >&2; exit 1; }
	$(PYTEST) $(T) -q --tb=short

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
	$(RUFF)
	$(BLACK)
	$(MYPY)

info:
	$(REEARTH) info

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .ruff_cache
	@echo "OK tools clean"
