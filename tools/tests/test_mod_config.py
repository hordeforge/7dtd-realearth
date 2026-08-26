"""Tests for realearth.mod_config (shared config writer for install scripts)."""

from __future__ import annotations

import json
from pathlib import Path

from realearth import mod_config

ROOT = Path(__file__).resolve().parents[2]


def write_config(tmp_path: Path, argv: list[str]) -> dict:
    dest = tmp_path / "dest"
    missing_root = str(ROOT / "Config" / "_missing_root_for_test")
    rc = mod_config.main(["write", str(dest), missing_root, *argv])
    assert rc == 0
    return json.loads((dest / "Config" / "realearth.json").read_text(encoding="utf-8"))


def test_parse_scalar_types():
    assert mod_config.parse_scalar("true") is True
    assert mod_config.parse_scalar("false") is False
    assert mod_config.parse_scalar("512") == 512
    assert mod_config.parse_scalar("11000.5") == 11000.5
    assert mod_config.parse_scalar("Streamed") == "Streamed"
    assert mod_config.parse_scalar("Data/tiles") == "Data/tiles"
    assert mod_config.parse_scalar("") is None


def test_override_set_and_setdefault(tmp_path: Path):
    cfg = write_config(
        tmp_path,
        [
            "--fresh",
            "MapMode=Streamed",
            "EngineMaxGameY=11000",
            "LocalWindowSize?=1024",
        ],
    )
    assert cfg["MapMode"] == "Streamed"
    assert cfg["EngineMaxGameY"] == 11000
    # Empty fresh base: ?= fills the absent key.
    assert cfg["LocalWindowSize"] == 1024


def test_setdefault_keeps_explicit_value(tmp_path: Path):
    cfg = write_config(tmp_path, ["--fresh", "StreamRadiusTiles=4", "StreamRadiusTiles?=3"])
    # Explicit set wins over a later ?= default.
    assert cfg["StreamRadiusTiles"] == 4


def test_sync_manifest_dimensions_and_bbox(tmp_path: Path):
    dest = tmp_path / "dest"
    tiles = dest / "Data" / "tiles"
    tiles.mkdir(parents=True)
    (tiles / "earth.manifest.json").write_text(
        json.dumps(
            {
                "world_width": 2048,
                "world_height": 1024,
                "tile_size": 256,
                "bbox": {"west": -122.5, "south": 37.0, "east": -121.0, "north": 38.5},
            }
        ),
        encoding="utf-8",
    )
    cfg: dict = {}
    for pair in (
        "WorldWidth=512",
        "WorldHeight=512",
        "TileSize=512",
        "LocalWindowSize=512",
    ):
        mod_config.apply_override(cfg, pair)
    assert mod_config.sync_manifest_dimensions(dest, cfg, include_bbox=True)
    assert cfg["WorldWidth"] == 2048
    assert cfg["WorldHeight"] == 1024
    assert cfg["TileSize"] == 256
    assert cfg["LocalWindowSize"] == 1024
    assert cfg["BboxWest"] == -122.5
    assert cfg["BboxNorth"] == 38.5


def test_height_test_meta_spawn_and_ceiling(tmp_path: Path):
    dest = tmp_path / "dest"
    tiles = dest / "Data" / "tiles"
    tiles.mkdir(parents=True)
    (tiles / "height_test.json").write_text(
        json.dumps({"summit_lon": -121.7, "summit_lat": 46.85, "engine_max_game_y": 8849}),
        encoding="utf-8",
    )
    cfg: dict = {"EngineMaxGameY": 11000}
    mod_config.apply_height_test_meta(dest, cfg)
    assert cfg["SpawnLongitude"] == -121.7
    assert cfg["SpawnLatitude"] == 46.85
    assert cfg["DefaultSpawnLon"] == -121.7
    assert cfg["DefaultSpawnLat"] == 46.85
    # Staged ceiling above 500 replaces the default.
    assert cfg["EngineMaxGameY"] == 8849


def test_height_test_meta_low_ceiling_keeps_default(tmp_path: Path):
    dest = tmp_path / "dest"
    tiles = dest / "Data" / "tiles"
    tiles.mkdir(parents=True)
    (tiles / "height_test.json").write_text(
        json.dumps({"engine_max_game_y": 500}), encoding="utf-8"
    )
    cfg: dict = {"EngineMaxGameY": 11000}
    mod_config.apply_height_test_meta(dest, cfg)
    assert cfg["EngineMaxGameY"] == 11000
