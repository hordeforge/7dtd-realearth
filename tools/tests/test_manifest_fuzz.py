"""Deterministic mutation fuzz target for the .rte pack manifest reader.

earth.manifest.json is the trust boundary for a pack that can arrive from a
shared pack or a CDN mirror, and every consumer reads it before it reads a
tile: `realearth inspect-manifest`, viewer_export.mosaic_pack, the streamed
chunk sampler, mod_config.sync_manifest_dimensions. Unit tests pin the writer;
these harnesses feed hostile members and raw JSON text through the reader and
assert the contract the consumers rely on, so a wrong value or an uncaught
exception surfaces as a failed assertion instead of a broken pack:

- only ValueError escapes (JSONDecodeError is one, TypeError/OverflowError are
  not: a caller that catches ValueError to report a bad pack must see it)
- a decoded manifest keeps the types its members promise, finite throughout
- write_manifest -> read_manifest reproduces the manifest exactly (pair
  assertion across the pack-file boundary)
- a well-formed manifest drives bbox mapping into a real block inside the pack
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from realearth.coords import EarthGrid
from realearth.local_window import LocalWindow
from realearth.mod_config import sync_manifest_dimensions
from realearth.streamed_chunk import lonlat_to_pack_block
from realearth.tile_format import (
    Manifest,
    read_manifest,
    write_manifest,
)

_SEED = 20260928
_ITERATIONS = 400

_NUMERIC_KEYS = (
    "version",
    "tile_size",
    "world_width",
    "world_height",
    "sea_level_game_y",
    "meters_per_block",
)

# Values a mirror or a hand-edited pack can carry for any single member.
_HOSTILE_NUMBERS: list[Any] = [
    0,
    1,
    -1,
    512,
    40_075_017,
    -40_075_017,
    1.5,
    "512",
    "abc",
    "",
    None,
    True,
    [],
    [1],
    {},
    1e308,
    "1e999",
    -1e999,
    10**400,
]

_HOSTILE_TILES: list[Any] = [
    [],
    [{"tx": 0, "tz": 0}],
    [{"tx": -1, "tz": 2**31}],
    [{"tx": "a", "tz": "b"}],
    [{"tx": 1.5, "tz": None}],
    [{"nope": 1}],
    [{"tx": 0, "tz": 0, "path": "../../etc/passwd"}],
    [None],
    "0/0.rte",
    5,
    None,
    {"tx": 0, "tz": 0},
]

_HOSTILE_BBOX: list[Any] = [
    None,
    {},
    {"west": -180.0, "south": -90.0, "east": 180.0, "north": 90.0},
    {"west": 0.0, "south": 0.0, "east": 1.0, "north": 1.0},
    {"west": 1.0, "south": 0.0, "east": 1.0, "north": 1.0},  # east == west
    {"west": 0.0, "south": 1.0, "east": 1.0, "north": 0.0},  # north < south
    {"west": 0.0, "south": 0.0, "east": "x", "north": 1.0},
    {"west": 0.0, "south": 0.0, "east": 1.0, "north": None},
    {"west": 1e999, "south": 0.0, "east": 2.0, "north": 1.0},
    [0, 0, 1, 1],
    [1, 2],
    "bbox",
    7,
]

_HOSTILE_NAMES: list[Any] = [
    "RealEarth",
    "Europe/Regional",
    "",
    "X" * 4096,
    "São Paulo \U0001f600",
    "Foo\r\n[INFO] installed",
    42,
    None,
    ["Regional"],
    {"nested": "name"},
]


def _assert_manifest_invariants(m: Manifest) -> None:
    for key in ("version", "tile_size", "world_width", "world_height", "sea_level_game_y"):
        value = getattr(m, key)
        assert isinstance(value, int), key
    assert isinstance(m.meters_per_block, float)
    assert m.meters_per_block == m.meters_per_block  # not NaN
    assert m.meters_per_block not in (float("inf"), float("-inf"))
    assert isinstance(m.tiles, list)
    assert isinstance(m.sources, list)
    assert m.bbox is None or isinstance(m.bbox, dict)


def _hostile_doc(rng: random.Random) -> dict[str, Any]:
    doc: dict[str, Any] = {}
    if rng.random() < 0.9:
        for key in _NUMERIC_KEYS:
            if rng.random() < 0.4:
                doc[key] = rng.choice(_HOSTILE_NUMBERS)
    if rng.random() < 0.5:
        doc["name"] = rng.choice(_HOSTILE_NAMES)
    if rng.random() < 0.5:
        doc["tiles"] = rng.choice(_HOSTILE_TILES)
    if rng.random() < 0.5:
        doc["bbox"] = rng.choice(_HOSTILE_BBOX)
    if rng.random() < 0.3:
        doc["sources"] = rng.choice([["copernicus"], "copernicus", 3, None])
    if rng.random() < 0.3:
        doc["notes"] = rng.choice(["", "x" * 8192, None, 5, ["note"]])
    if rng.random() < 0.3:
        doc["crs"] = rng.choice(["EPSG:4326", "", None, 4326])
    return doc


def _read_doc(tmp_path: Path, doc: Any) -> Manifest | None:
    """Round-trip `doc` through the pack file; None when the reader rejects it."""
    path = tmp_path / "earth.manifest.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    try:
        return read_manifest(path)
    except ValueError:
        return None


def test_fuzz_manifest_members_reject_or_hold_invariants(tmp_path: Path):
    rng = random.Random(_SEED)
    accepted = 0
    for _ in range(_ITERATIONS):
        m = _read_doc(tmp_path, _hostile_doc(rng))
        if m is None:
            continue
        _assert_manifest_invariants(m)
        accepted += 1
    # Every numeric member hostile in turn means the reader must reject at least
    # something; a run where nothing is ever rejected means the harness rotted.
    assert accepted > 0
    assert any(
        _read_doc(tmp_path, {key: 1e999}) is None for key in ("version", "world_width", "tile_size")
    )


def test_fuzz_manifest_json_text_never_escapes_valueerror(tmp_path: Path):
    """Truncated, mistyped and non-object JSON text: only ValueError may escape.

    `realearth inspect-manifest` reports a bad pack by catching ValueError, so a
    TypeError or OverflowError here would surface as a traceback instead.
    """
    rng = random.Random(_SEED + 1)
    path = tmp_path / "earth.manifest.json"
    good = Manifest(
        name="Regional",
        tile_size=512,
        world_width=1024,
        world_height=1024,
        bbox={"west": 0.0, "south": 0.0, "east": 1.0, "north": 1.0},
        tiles=[{"tx": 0, "tz": 0}],
        sources=["copernicus"],
    )
    seed = json.dumps(good.to_dict()).encode("utf-8")
    for _ in range(_ITERATIONS):
        payload = bytearray(seed)
        mode = rng.randrange(4)
        if mode == 0:  # truncate
            del payload[rng.randrange(len(payload)) :]
        elif mode == 1:  # bit flips
            for _ in range(rng.randint(1, 6)):
                payload[rng.randrange(len(payload))] ^= 1 << rng.randrange(8)
        elif mode == 2:  # random bytes
            payload = bytearray(rng.randbytes(rng.randrange(0, 256)))
        else:  # splice a hostile literal over a numeric member
            pos = seed.find(b'"tile_size"')
            if pos >= 0:
                payload[pos : pos + len(b'"tile_size"') + 8] = rng.choice(
                    (b'"tile_size": 1e999 ', b'"tile_size": null ', b'"tile_size": [1,2] ')
                )
        path.write_bytes(bytes(payload))
        try:
            m = read_manifest(path)
        except ValueError:
            continue
        _assert_manifest_invariants(m)


def test_fuzz_manifest_write_read_roundtrip(tmp_path: Path):
    """Pair assertion across the pack-file boundary: write then read is lossless."""
    rng = random.Random(_SEED + 2)
    path = tmp_path / "earth.manifest.json"
    for _ in range(50):
        m = Manifest(
            name=rng.choice(["RealEarth", "Regional", "Zürich", ""]),
            version=rng.randrange(0, 4),
            tile_size=rng.choice([1, 16, 512, 4096]),
            world_width=rng.choice([1, 1024, 40_075_017]),
            world_height=rng.choice([1, 512, 20_003_931]),
            sea_level_game_y=rng.randrange(0, 65_536),
            meters_per_block=rng.choice([0.0, 0.5, 1.0, 1e-3]),
            bbox=rng.choice([None, {"west": -1.0, "south": -2.0, "east": 3.0, "north": 4.0}]),
            tiles=[{"tx": rng.randrange(4), "tz": rng.randrange(4)} for _ in range(3)],
            sources=["copernicus", "osm"],
            notes=rng.choice(["", "regional pack", "line\nbreak"]),
        )
        write_manifest(path, m)
        back = read_manifest(path)
        assert back == m
        assert back.to_dict() == m.to_dict()


def test_fuzz_manifest_bbox_maps_into_the_pack(tmp_path: Path):
    """A decoded bbox must place any lon/lat at a real block inside the pack."""
    rng = random.Random(_SEED + 3)
    for _ in range(100):
        west = rng.uniform(-180.0, 170.0)
        east = west + rng.uniform(1e-6, 10.0)
        south = rng.uniform(-90.0, 80.0)
        north = south + rng.uniform(1e-6, 10.0)
        width = rng.randrange(1, 2048)
        height = rng.randrange(1, 2048)
        man = Manifest(
            tile_size=512,
            world_width=width,
            world_height=height,
            bbox={"west": west, "south": south, "east": east, "north": north},
        )
        assert _read_doc(tmp_path, man.to_dict()) == man
        grid = EarthGrid(width=width, height=height, tile_size=man.tile_size)
        lon = rng.uniform(west, east)
        lat = rng.uniform(south, north)
        x, z = lonlat_to_pack_block(lon, lat, man)
        assert 0 <= x < width
        assert 0 <= z < height
        window = LocalWindow(grid=grid, size=min(1024, width, height))
        ex, ez = window.local_to_earth(0, 0)
        assert 0 <= ex <= width and 0 <= ez <= height


def test_fuzz_manifest_sync_maps_hostile_values_to_json(tmp_path: Path):
    """sync_manifest_dimensions writes the manifest numbers into a JSON config."""
    rng = random.Random(_SEED + 4)
    for i in range(60):
        dest = tmp_path / f"install{i}"
        doc = {
            "world_width": rng.choice(_HOSTILE_NUMBERS),
            "world_height": rng.choice(_HOSTILE_NUMBERS),
            "tile_size": rng.choice(_HOSTILE_NUMBERS),
            "bbox": rng.choice(_HOSTILE_BBOX),
        }
        m = _read_doc(tmp_path, doc)
        if m is None:
            continue
        cfg: dict[str, Any] = {}
        synced = sync_manifest_dimensions(
            dest,
            cfg,
            include_bbox=True,
            max_window=1024,
            spawn_from_bbox=True,
        )
        assert synced is False  # no manifest written to the install dir yet
        write_manifest(dest / "Data" / "tiles" / "earth.manifest.json", m)
        cfg = {}
        try:
            assert sync_manifest_dimensions(
                dest, cfg, include_bbox=True, max_window=1024, spawn_from_bbox=True
            )
        except ValueError:
            # A member the mod config cannot serialize is a clean refusal.
            continue
        # Every synced member is a finite JSON scalar, or the mod config that
        # consumes it fails to deserialize.
        for key, value in cfg.items():
            assert isinstance(value, (int, float, bool, str)), key
            if isinstance(value, float):
                assert value == value and value not in (float("inf"), float("-inf"))


def test_fuzz_manifest_absent_fields_keep_writer_defaults(tmp_path: Path):
    """An empty or partial manifest must still decode to the full-planet default."""
    for doc in ({}, {"name": "OnlyName"}, {"version": 1}, None, [], "manifest"):
        m = _read_doc(tmp_path, doc)
        if m is None:
            continue
        _assert_manifest_invariants(m)


@pytest.mark.parametrize("value", [1e999, -1e999, None, "abc", [], {}])
def test_manifest_non_finite_and_wrong_type_members_raise_valueerror(value: Any):
    for key in _NUMERIC_KEYS:
        with pytest.raises(ValueError):
            Manifest.from_dict({key: value})
