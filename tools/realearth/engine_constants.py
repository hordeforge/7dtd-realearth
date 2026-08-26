"""Audit vanilla 7DTD vertical engine constants from Assembly-CSharp.dll.

These are compile-time literals on 3.0.x (WorldConstants.ChunkBlockYDim=256).
Used by `realearth engine-audit` and tests so we fail loudly if TFP changes dims.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from realearth.proton_paths import client_game_dir

# Known-good 3.0.1 values (also defaults when dnfile is absent; install the
# `audit` extra for a live read)
VANILLA_3_0_1 = {
    "ChunkBlockYDim": 256,
    "ChunkBlockYPow": 8,
    "ChunkBlockLayers": 64,
    "ChunkBlockLayerHeight": 4,
    "ChunkDensityYDim": 256,
    "cMaxHeight": 255,
}


def default_game_dll() -> Path:
    return client_game_dir() / "7DaysToDie_Data/Managed/Assembly-CSharp.dll"


def read_int32_constants(dll: Path) -> dict[str, int]:
    """Return name→int32 for Constant table entries of interest (Field parents only)."""
    import dnfile

    pe = dnfile.dnPE(str(dll))
    want = set(VANILLA_3_0_1.keys()) | {
        "ChunkBlockXDim",
        "ChunkBlockZDim",
        "ChunkMeshLayerHeight",
        "ChunkBlockLayerHeightPow",
        "ChunkBlockYDimM1",
    }
    out: dict[str, int] = {}
    for row in pe.net.mdtables.Constant:
        try:
            parent_row = row.Parent.row
            # Skip Param/Property constants; we want Field literals (WorldConstants etc.)
            if parent_row.__class__.__name__ not in ("FieldRow",):
                continue
            name_obj = parent_row.Name
            name = getattr(name_obj, "value", None) or str(name_obj)
        except Exception:
            continue
        if name not in want:
            continue
        raw = row.Value
        b = getattr(raw, "value", None)
        if callable(b):
            b = b()
        if b is None and hasattr(raw, "value_bytes"):
            vb = raw.value_bytes
            b = vb() if callable(vb) else vb
        if isinstance(b, memoryview):
            b = b.tobytes()
        if not isinstance(b, (bytes, bytearray)) or len(b) < 4:
            continue
        # First Field win for duplicate names (cLayerHeight appears on multiple types)
        if name in out:
            continue
        out[name] = struct.unpack_from("<i", b, 0)[0]
    return out


def audit_engine_height(dll: Path | None = None) -> dict[str, Any]:
    path = Path(dll) if dll else default_game_dll()
    result: dict[str, Any] = {
        "dll": str(path),
        "exists": path.is_file(),
        "constants": {},
        "vanilla_y_dim": VANILLA_3_0_1["ChunkBlockYDim"],
        "needs_engine_mod_for_taller": True,
        "notes": [],
    }
    if not path.is_file():
        result["notes"].append("Assembly-CSharp.dll not found; using documented 3.0.1 defaults")
        result["constants"] = dict(VANILLA_3_0_1)
        return result

    try:
        consts = read_int32_constants(path)
    except ImportError as ex:
        result["notes"].append(f"dnfile missing ({ex}); live audit needs: uv sync --extra audit")
        result["constants"] = dict(VANILLA_3_0_1)
        return result
    except Exception as ex:
        result["notes"].append(f"dnfile read failed: {ex}")
        result["constants"] = dict(VANILLA_3_0_1)
        return result

    result["constants"] = consts
    ydim = consts.get("ChunkBlockYDim", VANILLA_3_0_1["ChunkBlockYDim"])
    result["vanilla_y_dim"] = ydim
    if ydim <= 256:
        result["needs_engine_mod_for_taller"] = True
        result["notes"].append(
            f"ChunkBlockYDim={ydim}: stock column height, run `make engine-expand` "
            "to patch Assembly-CSharp for 1:1 tall columns"
        )
    else:
        result["needs_engine_mod_for_taller"] = False
        result["notes"].append(
            f"ChunkBlockYDim={ydim}: engine height expand active (RealEarth patch)"
        )
    # Consistency: layers * layerHeight should equal YDim
    layers = consts.get("ChunkBlockLayers")
    lh = consts.get("ChunkBlockLayerHeight")
    if layers and lh and layers * lh != ydim:
        result["notes"].append(
            f"warning: ChunkBlockLayers*{lh}={layers * lh} != ChunkBlockYDim={ydim}"
        )
    return result
