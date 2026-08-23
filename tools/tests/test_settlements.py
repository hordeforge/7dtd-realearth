"""Text-handling invariants: NFC normalization, UTF-8 storage, POI blob round-trip."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from realearth.settlements import (
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
