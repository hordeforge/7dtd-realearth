"""Deterministic mutation fuzz targets for the settlement parsers.

Both entry points here read external, untrusted data: a GeoJSON file handed to
`realearth bake-world --settlements` (downloaded map data, a pack from a mirror)
and the POI blob inside a .rte tile. Unit tests pin known-bad shapes; these
harnesses explore around them with seeded, reproducible mutations and assert
parser invariants, so a logic bug surfaces as a failed assertion instead of a
silent wrong city:

- the GeoJSON loader returns settlements that are all real positions on the
  globe, with non-negative population and control-free names, or raises
  ValueError (the only error its contract allows)
- the POI decoder returns dict entries or raises ValueError
- decode(encode(plan)) reproduces the plan exactly (pair assertion across the
  encode/decode boundary)
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from realearth.settlements import (
    LAT_LIMIT,
    LON_LIMIT,
    MAX_POI_BLOB_BYTES,
    Settlement,
    decode_poi_blob,
    encode_poi_blob,
    load_settlements_geojson,
    normalize_place_name,
)

_SEED = 20260827
_ITERATIONS = 300

_HOSTILE_NAMES = [
    "São Paulo",
    "Xi'an",
    "",
    "\U0001f600",
    "A" * 512,
    "Foo\r\n[INFO] admin logged in",
    "Zürich",
    "\x00\x7f\u0085",
    "مراكش",
]
_HOSTILE_NUMBERS = [0, -5, 1, 1.5, "abc", "", None, True, [], {}, 1e308, "1e999", -1e308]
_HOSTILE_GEOMETRIES = [
    {"type": "Point", "coordinates": [1.0, 2.0]},
    {"type": "Point", "coordinates": [0.0, 0.0, 12.5]},
    {"type": "Point", "coordinates": []},
    {"type": "Point", "coordinates": [1.0]},
    {"type": "Point", "coordinates": ["x", "y"]},
    {"type": "Point", "coordinates": {"lon": 1}},
    {"type": "Point", "coordinates": [None, 5]},
    {"type": "Point", "coordinates": [1e999, 1e999]},
    {"type": "Point", "coordinates": [LON_LIMIT + 1, 0.0]},
    {"type": "Point", "coordinates": [0.0, LAT_LIMIT + 1]},
    {"type": "Point", "coordinates": [True, False]},
    {"type": "Polygon", "coordinates": [[[1.0, 2.0], [3.0, 4.0], [5.0, 2.0], [1.0, 2.0]]]},
    {"type": "Polygon", "coordinates": []},
    {"type": "Polygon", "coordinates": [[[1.0, 2.0]], [[[[3.0, 4.0]]]]]},
    {"type": "MultiPolygon", "coordinates": [[[[1.0, 2.0], [3.0, 4.0]]]]},
    {"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]]},
    {"type": None, "coordinates": None},
    {},
    "Point",
    None,
    [1, 2],
]
_HOSTILE_PROPERTIES = [
    {},
    {"name": "Testville", "population": 1200},
    {"NAME": "Upper", "POP_MAX": "9000"},
    {"name": "Bad", "population": "abc"},
    {"name": 42, "kind": ["a"]},
    {"name": "Boxed", "bbox": [1.0, 2.0, 3.0, 4.0]},
    {"name": "Boxed", "bbox": ["a", "b", "c", "d"]},
    {"name": "Boxed", "bbox": [1e999, 1, 2, 3]},
    {"name": "Boxed", "extent": (1, 2, 3, 4)},
    {"name": "Extent", "edge_radius_m": "huge"},
    {"name": "Extent", "edge_radius_km": -1},
    {"name": "Extent", "west": 1, "south": 2, "east": "x", "north": 4},
    {"name": "Extent", "radius_m": 1e999},
]


def _assert_settlement_invariants(s: Settlement) -> None:
    assert -LON_LIMIT <= s.lon <= LON_LIMIT
    assert -LAT_LIMIT <= s.lat <= LAT_LIMIT
    assert s.lon == s.lon and s.lat == s.lat  # not NaN
    assert s.population >= 0
    assert isinstance(s.population, int)
    assert normalize_place_name(s.name) == s.name
    assert s.edge_radius_m is None or (
        s.edge_radius_m == s.edge_radius_m and s.edge_radius_m >= 0.0
    )


def _load(tmp_path: Path, doc: Any) -> list[Settlement]:
    """Run the loader; return its settlements, or [] for a rejected document."""
    path = tmp_path / "fuzz.geojson"
    path.write_text(json.dumps(doc), encoding="utf-8")
    try:
        return load_settlements_geojson(path)
    except ValueError:
        return []


def test_fuzz_geojson_features_reject_or_yield_valid_settlements(tmp_path: Path):
    rng = random.Random(_SEED)
    seen = 0
    for _ in range(_ITERATIONS):
        doc: Any = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": rng.choice(_HOSTILE_GEOMETRIES),
                    "properties": rng.choice(_HOSTILE_PROPERTIES),
                }
                for _ in range(rng.randrange(1, 6))
            ],
        }
        if rng.random() < 0.15:
            doc = rng.choice([None, [], "nope", {"type": "FeatureCollection"}, doc])
        for s in _load(tmp_path, doc):
            _assert_settlement_invariants(s)
            seen += 1
    # A run where nothing ever parsed means the harness rotted.
    assert seen > 0


def test_fuzz_geojson_deeply_nested_rings_do_not_blow_the_stack(tmp_path: Path):
    # Recursive ring flattening turned this into a RecursionError that killed
    # the build; the walk is iterative and depth-capped, so nesting is skipped.
    node: Any = [1.0, 2.0]
    for _ in range(5000):
        node = [node]
    for gtype in ("Polygon", "MultiPolygon"):
        doc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": gtype, "coordinates": node},
                    "properties": {"name": "Deep"},
                },
                # a real ring alongside it must still parse
                {
                    "type": "Feature",
                    "geometry": {
                        "type": gtype,
                        "coordinates": [[[1.0, 2.0], [3.0, 4.0], [5.0, 2.0]]],
                    },
                    "properties": {"name": "Real", "population": 10},
                },
            ],
        }
        out = _load(tmp_path, doc)
        assert [s.name for s in out] == ["Real"]
        _assert_settlement_invariants(out[0])


def test_fuzz_geojson_text_mutation_never_escapes_valueerror(tmp_path: Path):
    rng = random.Random(_SEED + 1)
    path = tmp_path / "fuzz.geojson"
    for _ in range(_ITERATIONS):
        payload = rng.randbytes(rng.randrange(0, 512))
        if rng.random() < 0.6:  # half start from a document the loader accepts
            payload = b'{"features":[]}' + payload[payload.find(b"}") :]
        path.write_bytes(payload)
        try:
            out = load_settlements_geojson(path)
        except ValueError:
            continue
        for s in out:
            _assert_settlement_invariants(s)


def test_fuzz_poi_blob_rejects_or_returns_dicts():
    rng = random.Random(_SEED + 2)
    plan = [
        {
            "name": rng.choice(_HOSTILE_NAMES),
            "band": rng.choice(["town", "city", "wilderness", "MIXED case"]),
            "local_x": rng.randrange(-5, 5),
            "local_z": rng.randrange(-5, 5),
        }
        for _ in range(rng.randrange(4))
    ]
    # Pair assertion first: the decoder must agree with the encoder.
    assert decode_poi_blob(encode_poi_blob(plan)) == plan

    corpus = [
        encode_poi_blob(plan),
        b"{}",
        b'{"pois":[]}',
        b'{"pois":[{"name":"x"}]}',
        b'{"pois":null}',
        b"null",
        b"[]",
        b"5",
        b'{"pois":[1,"a",null,{"name":"kept"}]}',
        "\ufeff{}".encode(),
    ]
    for i in range(_ITERATIONS):
        blob = bytearray(rng.choice(corpus))
        mode = i % 4
        if mode == 0:  # truncate
            del blob[rng.randrange(len(blob)) :]
        elif mode == 1:  # bit flips
            for _ in range(rng.randint(1, 6)):
                blob[rng.randrange(len(blob))] ^= 1 << rng.randrange(8)
        elif mode == 2:  # replace with a random-length string payload
            blob = bytearray(rng.randbytes(rng.randrange(0, 64)))
        else:  # raw bytes never form valid JSON
            blob = bytearray(rng.randbytes(rng.randrange(1, 64)))
        try:
            out = decode_poi_blob(bytes(blob))
        except ValueError:
            continue
        assert all(isinstance(p, dict) for p in out)


@pytest.mark.parametrize(
    "blob",
    [
        b"null",
        b"[]",
        b"5",
        b'{"pois":5}',
        b'{"pois":{"a":1}}',
        b"\xff\xfe",
        b"{",
    ],
)
def test_decode_poi_blob_rejects_malformed_payloads(blob: bytes):
    with pytest.raises(ValueError):
        decode_poi_blob(blob)


def test_decode_poi_blob_rejects_oversized_payload():
    with pytest.raises(ValueError):
        decode_poi_blob(b"{" + b" " * (MAX_POI_BLOB_BYTES + 1) + b"}")


def test_fuzz_place_names_stay_log_safe():
    """Names reach the dedicated server log; every code point survives filtering
    as itself, so no combination can smuggle CR/LF or a control char through."""
    rng = random.Random(_SEED + 3)
    for _ in range(_ITERATIONS):
        raw = "".join(
            chr(rng.randrange(0, 0x2FFF)) for _ in range(rng.randrange(0, 32))
        ) + rng.choice(_HOSTILE_NAMES)
        clean = normalize_place_name(raw)
        assert not any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in clean)
        assert normalize_place_name(clean) == clean
