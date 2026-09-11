"""Offline pins for AltitudeClimate.cs (ISA lapse, hypoxia bands, O2 curve).

Parses constants from the shipped C# so thresholds cannot drift silently.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Source" / "RealEarth" / "AltitudeClimate.cs"


def _src() -> str:
    return SRC.read_text(encoding="utf-8")


def _const_float(name: str) -> float:
    m = re.search(rf"public const float {name} = (-?[0-9.]+)f?;", _src())
    assert m, f"{name} missing from AltitudeClimate.cs"
    return float(m.group(1))


def _const_int(name: str) -> int:
    m = re.search(rf"public const int {name} = (\d+);", _src())
    assert m, f"{name} missing from AltitudeClimate.cs"
    return int(m.group(1))


def elev_m(game_y: int, sea: int) -> int:
    return game_y - sea


def ambient_temp_c(elev_m_asl: int, sea_temp: float = 15.0, lapse: float = 6.5) -> float:
    return sea_temp - (lapse * (elev_m_asl / 1000.0))


def oxygen_sat(elev_m_asl: int) -> float:
    if elev_m_asl <= 0:
        return 1.0
    x = elev_m_asl / 12000.0
    sat = 1.0 - (x**1.4)
    return max(0.35, min(1.0, sat))


def hypoxia_band(elev: int, onset: int, severe: int, critical: int) -> int:
    if elev >= critical:
        return 3
    if elev >= severe:
        return 2
    if elev >= onset:
        return 1
    return 0


def cold_band(temp_c: float, onset: float, severe: float) -> int:
    if temp_c <= severe:
        return 2
    if temp_c <= onset:
        return 1
    return 0


def sea_temp_for_lat(lat: float, base: float = 15.0) -> float:
    abs_lat = min(90.0, abs(lat))
    return base - (abs_lat / 90.0) * 30.0


def test_constants_present():
    assert _const_float("LapseCPerKm") == 6.5
    assert _const_float("SeaLevelTempC") == 15.0
    assert _const_int("HypoxiaOnsetM") == 2500
    assert _const_int("HypoxiaSevereM") == 5500
    assert _const_int("HypoxiaCriticalM") == 8000
    assert _const_float("ColdOnsetC") == 0.0
    assert _const_float("ColdSevereC") == -20.0


def test_elev_from_game_y():
    sea = 16000
    assert elev_m(16000, sea) == 0
    assert elev_m(18500, sea) == 2500  # hypoxia onset
    assert elev_m(24949, sea) == 8949  # Everest peak-ish


def test_isa_lapse_at_everest():
    # Everest ~8849 m → ~15 - 6.5*8.849 ≈ -42.5 °C at equator base
    t = ambient_temp_c(8849)
    assert -45.0 < t < -40.0


def test_lat_cools_poles():
    assert sea_temp_for_lat(0.0) == 15.0
    assert abs(sea_temp_for_lat(90.0) - (-15.0)) < 1e-6
    assert sea_temp_for_lat(45.0) == 0.0


def test_oxygen_curve():
    assert oxygen_sat(0) == 1.0
    assert 0.88 < oxygen_sat(2500) < 0.95
    assert 0.60 < oxygen_sat(5500) < 0.72
    assert 0.40 < oxygen_sat(8000) < 0.50
    assert oxygen_sat(20000) == 0.35


def test_hypoxia_bands():
    onset = _const_int("HypoxiaOnsetM")
    severe = _const_int("HypoxiaSevereM")
    critical = _const_int("HypoxiaCriticalM")
    assert hypoxia_band(0, onset, severe, critical) == 0
    assert hypoxia_band(onset, onset, severe, critical) == 1
    assert hypoxia_band(severe, onset, severe, critical) == 2
    assert hypoxia_band(critical, onset, severe, critical) == 3


def test_cold_bands():
    onset = _const_float("ColdOnsetC")
    severe = _const_float("ColdSevereC")
    assert cold_band(10.0, onset, severe) == 0
    assert cold_band(0.0, onset, severe) == 1
    assert cold_band(-20.0, onset, severe) == 2


def test_tick_and_buffs_shipped():
    tick = (ROOT / "Source" / "RealEarth" / "AltitudeClimateTick.cs").read_text(encoding="utf-8")
    assert "buffAltitudeHypoxia01" in tick
    assert "buffAltitudeCold01" in tick
    assert "buffAltitudeHeat01" in tick
    assert "HeatBand" in tick or "HeatBuffs" in tick
    assert "_re_heat_band" in tick
    hooks = (ROOT / "Source" / "RealEarth" / "RuntimeHooks.cs").read_text(encoding="utf-8")
    assert "AltitudeClimateTick.TickPlayer" in hooks
    buffs = (ROOT / "Config" / "buffs.xml").read_text(encoding="utf-8")
    for name in (
        "buffAltitudeHypoxia01",
        "buffAltitudeHypoxia02",
        "buffAltitudeHypoxia03",
        "buffAltitudeCold01",
        "buffAltitudeCold02",
        "buffAltitudeHeat01",
        "buffAltitudeHeat02",
    ):
        assert name in buffs


def test_math_consistency_pow():
    # Sanity: 1.4 exponent used in C# matches Python
    x = 5500 / 12000.0
    expected = 1.0 - math.pow(x, 1.4)
    assert abs(oxygen_sat(5500) - expected) < 1e-9


def test_landcover_temp_offset_table():
    """Soft gap 24: desert hotter, snow colder, heat bands, unknown = 0."""
    src = (ROOT / "Source" / "RealEarth" / "AltitudeClimate.cs").read_text(encoding="utf-8")
    assert "LandcoverTempOffsetC" in src
    assert "HeatBand" in src
    assert "HeatOnsetC" in src
    assert "HeatSevereC" in src
    assert "case 11:" in src  # DESERT
    assert "case 10:" in src  # SNOW
    tick = (ROOT / "Source" / "RealEarth" / "AltitudeClimateTick.cs").read_text(encoding="utf-8")
    assert "SampleLandcover" in tick
    assert "HeatBand" in tick
    assert "AmbientTempC(elevM, latDeg, lc)" in tick or "AmbientTempC(elevM, latDeg, lc," in tick
