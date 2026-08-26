"""RealEarth offline pipeline for 7 Days to Die."""

from typing import Any

__version__ = "0.3.0"

# JSON-shaped payloads (manifests, mod config, CLI summaries) that cross module
# and file boundaries. Values stay heterogeneous by definition of the format.
JsonDict = dict[str, Any]

# Equirectangular 1:1 mapping constants (WGS84 approx, meters as blocks).
EARTH_CIRCUMFERENCE_M = 40_075_017
EARTH_MERIDIAN_HALF_M = 20_003_931  # pole-to-pole arc length approx
DEFAULT_TILE_SIZE = 512
# A canvas this wide can only be planet-wide (Earth is ~40M blocks at 1 m/block),
# so it is the only case where X wraps at the antimeridian. Regional packs are
# orders of magnitude smaller and must clamp instead. Mirrors ModApi.cs.
PLANET_CANVAS_MIN_WIDTH = 10_000_000
# Local window the streamer keeps resident around the player, capped so a
# planet-wide canvas does not try to materialize as one window.
DEFAULT_LOCAL_WINDOW_SIZE = 1024
# Ocean surface game Y. ~100 leaves playable land columns without deep ocean floors.
DEFAULT_SEA_LEVEL_GAME_Y = 100
GAME_MAX_Y = 255  # stock 7DTD column
# Everest 8849 m + sea 100 + ~2 km fly-over headroom → 11000 game Y
EVEREST_METERS_ASL = 8849
FLY_OVER_HEADROOM_M = 2000
# 100 + 8849 + 2000 = 10949 → pad 51 → 11000
ENGINE_TARGET_MAX_Y = (
    DEFAULT_SEA_LEVEL_GAME_Y + EVEREST_METERS_ASL + FLY_OVER_HEADROOM_M + 51
)
