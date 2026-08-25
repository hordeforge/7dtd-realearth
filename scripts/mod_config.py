#!/usr/bin/env python3
"""Launcher for the RealEarth mod config writer.

The implementation lives in tools/realearth/mod_config.py next to its tests;
this launcher keeps `python3 scripts/mod_config.py ...` working for install
scripts on hosts without uv. Stdlib only.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = str(Path(__file__).resolve().parents[1] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from realearth.mod_config import main

if __name__ == "__main__":
    sys.exit(main())
