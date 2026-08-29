"""RealEarth offline pipeline for 7 Days to Die.

Module map (dependency direction: top imports bottom, never the reverse):
- coords, local_window          planet grid math, longitude wrap, sliding window
- elevation                     DEM fetch (open-meteo / terrarium)
- landcover, settlements, density   surface classification, POIs, population bands
- height, tile_format           real-meters-to-game-Y math, .rte tile codec
- streamed_chunk                fill one Streamed chunk from .rte samples
- region, generated_world, bake_world, height_test_map   world builders
- export_7dtd, viewer_export, viewer_server   pack export and web serving
- mod_config, server_config     XML config writers
- proton_paths, engine_constants, height_mod_case   install/engine integration
Entry point: python -m realearth.cli (see cli.py).
"""

from typing import Any

# Must match ModInfo.xml <Version> (the shipped mod version, CHANGELOG 0.x line);
# hatchling resolves the wheel/sdist version from here at build time.
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
# Ocean surface game Y. Anchored high so real below-sea relief (trenches
# down to ~-11 km) maps to positive game Y: 16000 - 11000 = 5000 floor, while
# ~12 km airliner cruise stays under the 32768 engine ceiling.
DEFAULT_SEA_LEVEL_GAME_Y = 16000
GAME_MAX_Y = 255  # stock 7DTD column
# Highest mountain, kept for peak math / docs even though the product ceiling
# is the airliner cruise band now.
EVEREST_METERS_ASL = 8849
# Commercial airliner cruise ceiling (~12 km ASL), not just Everest.
AIRLINER_CRUISE_M = 12000
FLY_OVER_HEADROOM_M = 1000
# sea(16000) + airliner(12000) + headroom(1000) = 29000 game Y
ENGINE_TARGET_MAX_Y = DEFAULT_SEA_LEVEL_GAME_Y + AIRLINER_CRUISE_M + FLY_OVER_HEADROOM_M
