"""Small targeted test case for the RealEarth engine height mod.

Run via:
  cd tools && uv run --locked python -m realearth.cli height-mod-test
  cd tools && uv run --locked pytest tests/test_height_mod_case.py -q

Checks (1 m ≈ 1 block, max = Everest + fly-over headroom):
  - ceiling constants
  - sea / Everest / fly-over mapping
  - trench floor clamp
  - stock 255 path still uint8
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from realearth import (
    DEFAULT_SEA_LEVEL_GAME_Y,
    ENGINE_TARGET_MAX_Y,
    EVEREST_METERS_ASL,
    FLY_OVER_HEADROOM_M,
)
from realearth.height import compress_elevation


@dataclass(frozen=True)
class CaseResult:
    name: str
    ok: bool
    detail: str


def _one_to_one(elev_m: float, *, sea: int = DEFAULT_SEA_LEVEL_GAME_Y) -> int:
    y = compress_elevation(
        np.array([elev_m], dtype=np.float64),
        sea_level_y=sea,
        max_y=ENGINE_TARGET_MAX_Y,
        min_y=1,
        profile="one_to_one",
        regional_exaggeration=1.0,
    )
    return int(y[0])


def run_height_mod_case() -> list[CaseResult]:
    """Execute the height-mod smoke case; returns per-check results."""
    results: list[CaseResult] = []

    # 1) Ceiling = sea + Everest + fly headroom (+ pad)
    expected_ceil = DEFAULT_SEA_LEVEL_GAME_Y + EVEREST_METERS_ASL + FLY_OVER_HEADROOM_M + 51
    ok = ENGINE_TARGET_MAX_Y == 11000 and expected_ceil == ENGINE_TARGET_MAX_Y
    results.append(
        CaseResult(
            "ceiling_constants",
            ok,
            f"ENGINE_TARGET_MAX_Y={ENGINE_TARGET_MAX_Y} "
            f"(sea={DEFAULT_SEA_LEVEL_GAME_Y} + everest={EVEREST_METERS_ASL} "
            f"+ fly={FLY_OVER_HEADROOM_M} + pad=51 → {expected_ceil})",
        )
    )

    # 2) Sea level 0 m ASL → game Y = sea
    sea_y = _one_to_one(0.0)
    results.append(
        CaseResult(
            "sea_level",
            sea_y == DEFAULT_SEA_LEVEL_GAME_Y,
            f"elev=0 m → gameY={sea_y} (want {DEFAULT_SEA_LEVEL_GAME_Y})",
        )
    )

    # 3) Everest summit
    everest_y = _one_to_one(float(EVEREST_METERS_ASL))
    want_everest = DEFAULT_SEA_LEVEL_GAME_Y + EVEREST_METERS_ASL  # 8949
    results.append(
        CaseResult(
            "everest_summit",
            everest_y == want_everest,
            f"elev={EVEREST_METERS_ASL} m → gameY={everest_y} (want {want_everest})",
        )
    )

    # 4) Fly over Everest: summit + half fly budget still under ceiling
    fly_elev = float(EVEREST_METERS_ASL + FLY_OVER_HEADROOM_M // 2)  # 8849 + 1000
    fly_y = _one_to_one(fly_elev)
    want_fly = DEFAULT_SEA_LEVEL_GAME_Y + int(fly_elev)
    results.append(
        CaseResult(
            "fly_over_everest",
            fly_y == want_fly and fly_y < ENGINE_TARGET_MAX_Y,
            f"elev={int(fly_elev)} m (summit+1 km) → gameY={fly_y} "
            f"(want {want_fly}, ceiling {ENGINE_TARGET_MAX_Y}, "
            f"air_left={ENGINE_TARGET_MAX_Y - fly_y})",
        )
    )

    # 5) Just under ceiling still maps; at/above elev that would exceed max clamps
    max_elev_before_clamp = ENGINE_TARGET_MAX_Y - DEFAULT_SEA_LEVEL_GAME_Y  # 10900
    at_cap = _one_to_one(float(max_elev_before_clamp))
    over = _one_to_one(float(max_elev_before_clamp + 5000))
    results.append(
        CaseResult(
            "ceiling_clamp",
            at_cap == ENGINE_TARGET_MAX_Y and over == ENGINE_TARGET_MAX_Y,
            f"elev={max_elev_before_clamp} → {at_cap}; "
            f"elev+5000 → {over} (both ≤ {ENGINE_TARGET_MAX_Y})",
        )
    )

    # 6) Deep trench clamps to min_y=1
    trench_y = _one_to_one(-11000.0)
    results.append(
        CaseResult(
            "trench_floor",
            trench_y == 1,
            f"elev=-11000 m → gameY={trench_y} (want min_y=1)",
        )
    )

    # 7) Air above summit before world lid (fly headroom)
    air_above_summit = ENGINE_TARGET_MAX_Y - everest_y
    results.append(
        CaseResult(
            "fly_headroom_blocks",
            air_above_summit >= FLY_OVER_HEADROOM_M,
            f"blocks above Everest surface={air_above_summit} (want ≥ {FLY_OVER_HEADROOM_M})",
        )
    )

    # 8) Stock short-column path still uint8 ≤ 250
    stock = compress_elevation(
        np.array([0.0, 5000.0]),
        max_y=250,
        profile="relative",
        regional_exaggeration=1.0,
    )
    results.append(
        CaseResult(
            "stock_short_column",
            stock.dtype == np.uint8 and int(stock.max()) <= 250,
            f"max_y=250 dtype={stock.dtype} max={int(stock.max())}",
        )
    )

    return results


def format_report(results: list[CaseResult] | None = None) -> str:
    results = results if results is not None else run_height_mod_case()
    lines = [
        "RealEarth height-mod test case",
        (
            f"  ceiling={ENGINE_TARGET_MAX_Y}  everest={EVEREST_METERS_ASL} m  "
            f"fly_headroom={FLY_OVER_HEADROOM_M} m  sea_y={DEFAULT_SEA_LEVEL_GAME_Y}"
        ),
        "",
    ]
    passed = 0
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        if r.ok:
            passed += 1
        lines.append(f"  [{mark}] {r.name}: {r.detail}")
    lines.append("")
    lines.append(f"  {passed}/{len(results)} checks passed")
    return "\n".join(lines) + "\n"


def all_passed(results: list[CaseResult] | None = None) -> bool:
    results = results if results is not None else run_height_mod_case()
    return all(r.ok for r in results)
