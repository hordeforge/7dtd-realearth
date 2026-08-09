"""RealEarth offline pipeline for 7 Days to Die."""

__version__ = "0.1.0"

# Equirectangular 1:1 mapping constants (WGS84 approx, meters as blocks).
EARTH_CIRCUMFERENCE_M = 40_075_017
EARTH_MERIDIAN_HALF_M = 20_003_931  # pole-to-pole arc length approx
DEFAULT_TILE_SIZE = 512
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
