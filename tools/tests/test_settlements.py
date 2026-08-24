"""Text-handling invariants: NFC normalization, UTF-8 storage, POI blob round-trip."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from realearth.settlements import (
    Settlement,
    decode_poi_blob,
    encode_poi_blob,
    load_settlements_geojson,
    normalize_place_name,
)


def test_normalize_place_name_folds_nfd_to_nfc():
    nfd = unicodedata.normalize("NFD", "São Paulo")
    assert nfd != "São Paulo"
    assert normalize_place_name(nfd) == "São Paulo"


def test_load_settlements_geojson_normalizes_name(tmp_path: Path):
    nfd_name = unicodedata.normalize("NFD", "São Paulo")
    gj = tmp_path / "s.geojson"
    gj.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-46.6, -23.5]},
                        "properties": {"name": nfd_name, "population": 12_000_000},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    settles = load_settlements_geojson(gj)
    assert settles[0].name == "São Paulo"


def test_encode_poi_blob_stores_real_utf8_and_round_trips():
    plan = [{"name": "São Paulo", "band": "metro", "local_x": 3, "local_z": 4}]
    blob = encode_poi_blob(plan)
    # No \uXXXX escapes: the name is stored as real UTF-8 bytes.
    assert "São Paulo".encode() in blob
    assert decode_poi_blob(blob)[0]["name"] == "São Paulo"


def test_encode_poi_blob_keeps_astral_characters_intact():
    name = "A\U0001F600B"  # astral-plane emoji (surrogate pair in UTF-16)
    blob = encode_poi_blob([{"name": name}])
    assert decode_poi_blob(blob)[0]["name"] == name


def test_population_band_ladder_matches_runtime_fallback():
    """One population→band ladder across offline writer and runtime fallback.

    Settlement.band (this file's producer, writes "band" into settlements.json /
    POI plans) and RuntimePoiInject.BandFromPop (C# runtime fallback for pack rows
    without a band) must agree exactly: band selects the runtime prefab pool, so
    the same population must stamp the same pool regardless of whether the pack
    row carried a band. The old producer ladder collapsed everything below 1000
    into hamlet, so a pop-50 place got hamlet cabins from a built pack but
    rural_scatter isolated POIs from a legacy row missing "band".
    """
    boundaries = [
        (999_999_999, "metro"),
        (1_000_000, "metro"),
        (999_999, "large_city"),
        (100_000, "large_city"),
        (99_999, "town"),
        (10_000, "town"),
        (9_999, "village"),
        (1_000, "village"),
        (999, "hamlet"),
        (100, "hamlet"),
        (99, "rural_scatter"),
        (50, "rural_scatter"),  # seed "Base Camp"
    ]
    for pop, want in boundaries:
        assert Settlement(name="x", lon=0.0, lat=0.0, population=pop).band == want, pop

    # Structural pin on the C# fallback ladder: same thresholds, same order.
    src = (
        (Path(__file__).resolve().parents[2] / "Source" / "RealEarth" / "RuntimePoiInject.cs")
        .read_text(encoding="utf-8")
    )
    body = src[src.index("static string BandFromPop") :]
    body = body[: body.index("}")]
    ladder = [
        (1_000_000, "metro"),
        (100_000, "large_city"),
        (10_000, "town"),
        (1_000, "village"),
        (100, "hamlet"),
    ]
    for pop, band in ladder:
        assert f"pop >= {pop:_d}" in body, f"runtime ladder missing {pop:_d}"
        assert f'return "{band}"' in body, f"runtime ladder missing {band}"
    assert 'return "rural_scatter"' in body
