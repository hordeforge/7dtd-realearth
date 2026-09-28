"""Tests for realearth.mod_config (shared config writer for install scripts)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_known_keys_cover_every_shipped_template():
    """The C# contract is the only key list, so templates must not outrun it."""
    known = mod_config.known_config_keys(ROOT)
    assert known, "RealEarthConfig.cs not found or has no [DataMember] properties"
    for name in ("realearth.json", "realearth.mp.json", "realearth.advanced_height.json"):
        cfg = json.loads((ROOT / "Config" / name).read_text(encoding="utf-8"))
        mod_config.reject_unknown_keys(cfg, known)


def test_write_rejects_misspelled_key(tmp_path: Path):
    """A typo would ship as a no-op: the loader ignores unknown members."""
    dest = tmp_path / "dest"
    with pytest.raises(SystemExit) as exc:
        mod_config.main(
            [
                "write",
                str(dest),
                str(ROOT),
                "--fresh",
                "EngineMaxGameY=11000",
                "EngineMaxGamY=29000",
            ]
        )
    assert "EngineMaxGamY" in str(exc.value)
    assert not (dest / "Config" / "realearth.json").exists()


def test_unknown_key_check_is_skipped_without_contract_source(tmp_path: Path):
    """A root without the C# source (installed tree) must not fail the write."""
    cfg = write_config(tmp_path, ["--fresh", "MapMode=Baked"])
    assert cfg["MapMode"] == "Baked"


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
    # Fixture ceiling above 500 AND above the configured value wins (monotonic):
    # 8849 > 11000? No, so the caller's 11000 stays. A product 29000 config is
    # never downgraded by a stale fixture hint.
    assert cfg["EngineMaxGameY"] == 11000


def test_height_test_meta_raises_ceiling_monotonically(tmp_path: Path):
    dest = tmp_path / "dest"
    tiles = dest / "Data" / "tiles"
    tiles.mkdir(parents=True)
    (tiles / "height_test.json").write_text(
        json.dumps({"engine_max_game_y": 29000}), encoding="utf-8"
    )
    cfg: dict = {"EngineMaxGameY": 29000}
    mod_config.apply_height_test_meta(dest, cfg)
    assert cfg["EngineMaxGameY"] == 29000


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


def test_help_documents_the_override_contract(capsys: pytest.CaptureFixture[str]) -> None:
    """--help carries the KEY=VALUE / KEY?=VALUE rule and a copyable example."""
    with pytest.raises(SystemExit) as exc:
        mod_config.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "KEY?=VALUE" in out
    assert "examples:" in out
    with pytest.raises(SystemExit):
        mod_config.main(["write", "--help"])
    assert "KEY[?]=VALUE" in capsys.readouterr().out


def test_missing_manifest_note_goes_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The `config ->` result line must not be preceded by a status note."""
    dest = tmp_path / "dest"
    rc = mod_config.main(["write", str(dest), str(ROOT / "Config" / "_missing"), "--sync-manifest"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "note: no manifest" in captured.err
    assert captured.out.startswith("config -> ")


def test_height_test_meta_rejects_non_finite_spawn(tmp_path: Path):
    """1e999 parses to inf; it must not reach the config as a spawn longitude.

    The manifest path already refuses non-finite members. The fixture path is
    the same untrusted input, so it gets the same guard.
    """
    dest = tmp_path / "dest"
    tiles = dest / "Data" / "tiles"
    tiles.mkdir(parents=True)
    (tiles / "height_test.json").write_text(
        '{"summit_lon": 1e999, "summit_lat": 46.85}', encoding="utf-8"
    )
    cfg: dict = {}
    with pytest.raises(ValueError, match="summit_lon"):
        mod_config.apply_height_test_meta(dest, cfg)
    assert "SpawnLongitude" not in cfg


def test_height_test_meta_rejects_non_object_file(tmp_path: Path):
    dest = tmp_path / "dest"
    tiles = dest / "Data" / "tiles"
    tiles.mkdir(parents=True)
    (tiles / "height_test.json").write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        mod_config.apply_height_test_meta(dest, {})


def test_truncated_manifest_is_a_clean_error_not_a_traceback(tmp_path: Path):
    """Install scripts read stderr only, so a truncated manifest must name itself."""
    dest = tmp_path / "dest"
    tiles = dest / "Data" / "tiles"
    tiles.mkdir(parents=True)
    (tiles / "earth.manifest.json").write_text('{"world_width": 512', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        mod_config.main(
            ["write", str(dest), str(tmp_path / "missing-root"), "--fresh", "--sync-manifest"]
        )
    message = str(exc.value)
    assert "not valid JSON" in message
    assert "earth.manifest.json" in message
    assert "Traceback" not in message


def test_truncated_height_test_fixture_is_a_clean_error(tmp_path: Path):
    dest = tmp_path / "dest"
    tiles = dest / "Data" / "tiles"
    tiles.mkdir(parents=True)
    (tiles / "height_test.json").write_text('{"summit_lon":', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        mod_config.main(
            ["write", str(dest), str(tmp_path / "missing-root"), "--fresh", "--height-test-meta"]
        )
    message = str(exc.value)
    assert "not valid JSON" in message
    assert "height_test.json" in message
    assert "Traceback" not in message
