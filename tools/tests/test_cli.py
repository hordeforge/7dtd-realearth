"""CLI contract tests: exit codes, clean errors, help consistency."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from realearth.cli import _display_text, _safe_name_component, main


def test_version_exits_zero() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "version" in result.stdout


@pytest.mark.parametrize(
    "hostile",
    [
        "\x1b]52;c;EVIL\x07",  # OSC 52 clipboard capture
        "\x1b[31mred\x1b[0m",  # ANSI color escape
        "bad\rOVERWRITE",  # carriage-return line rewrite
        "line1\nline2",  # newline injection
    ],
)
def test_display_text_strips_control_chars(hostile: str) -> None:
    safe = _display_text(hostile)
    assert all(ch.isprintable() for ch in safe)


def test_display_text_keeps_plain_names() -> None:
    assert _display_text("São Paulo") == "São Paulo"
    assert _display_text(42) == "42"


def test_safe_name_component_accepts_plain_names() -> None:
    assert (
        _safe_name_component({"name": "RealEarth_H500"}, "name", "Fallback")
        == "RealEarth_H500"
    )
    assert _safe_name_component({}, "name", "Fallback") == "Fallback"


@pytest.mark.parametrize(
    "bad",
    ["../../etc", "/etc/passwd", "a/b", "a\\b", "..", "."],
)
def test_safe_name_component_rejects_traversal(bad: str) -> None:
    with pytest.raises(ValueError):
        _safe_name_component({"name": bad}, "name", "Fallback")


def test_install_height_test_rejects_hostile_pack_name(tmp_path: Path) -> None:
    """Pack metadata name must never steer rmtree/copytree outside GeneratedWorlds."""
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "height_test.json").write_text(
        json.dumps({"name": "../../victim"}), encoding="utf-8"
    )
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("x", encoding="utf-8")
    from realearth.cli import _install_height_test

    with pytest.raises(ValueError, match="plain directory name"):
        _install_height_test(tmp_path, pack, tmp_path / "world")
    assert (victim / "keep.txt").is_file()


def test_unknown_command_is_usage_error() -> None:
    result = CliRunner().invoke(main, ["bogus"])
    assert result.exit_code == 2
    assert "No such command" in result.stderr


def test_lonlat_accepts_negative_coordinates() -> None:
    result = CliRunner().invoke(main, ["lonlat", "-74.006", "40.7128"])
    assert result.exit_code == 0
    assert "block:" in result.stdout
    assert "tile:" in result.stdout


def test_wrap_check_accepts_negative_x() -> None:
    result = CliRunner().invoke(main, ["wrap-check", "-1"])
    assert result.exit_code == 0
    assert "wrap_x(-1)" in result.stdout


def test_lonlat_still_rejects_non_numeric() -> None:
    result = CliRunner().invoke(main, ["lonlat", "abc", "0"])
    assert result.exit_code == 2
    assert "not a valid float" in result.stderr


def test_lonlat_converts() -> None:
    result = CliRunner().invoke(main, ["lonlat", "-74.006", "40.7128"])
    assert result.exit_code == 0
    assert "block:" in result.stdout
    assert "tile:" in result.stdout


def test_lonlat_rejects_infinite_lon() -> None:
    result = CliRunner().invoke(main, ["lonlat", "1e999", "40"])
    assert result.exit_code == 2
    assert "Traceback" not in result.stderr
    assert "LON" in result.stderr
    assert "finite" in result.stderr


def test_lonlat_rejects_nan_lat() -> None:
    result = CliRunner().invoke(main, ["lonlat", "-74", "nan"])
    assert result.exit_code == 2
    assert "Traceback" not in result.stderr
    assert "LAT" in result.stderr


def test_list_tiles_missing_manifest_is_clean_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["list-tiles", str(tmp_path)])
    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    assert "earth.manifest.json" in result.stderr
    assert "build-region" in result.stderr


def test_planet_tiles_valid_bbox() -> None:
    result = CliRunner().invoke(
        main,
        ["planet-tiles", "--west", "-105.3", "--south", "39.5",
         "--east", "-104.7", "--north", "40.0"],
    )
    assert result.exit_code == 0
    first, second = result.stdout.splitlines()[:2]
    count = int(first.split()[0])
    assert second.count(" ") == 1  # one "tx tz" pair per line
    assert len(result.stdout.splitlines()) - 1 <= count


def test_planet_tiles_rejects_inverted_bbox() -> None:
    result = CliRunner().invoke(
        main,
        ["planet-tiles", "--west", "10", "--south", "50", "--east", "5", "--north", "40"],
    )
    assert result.exit_code == 1
    assert "east>west" in result.stderr


def test_sample_chunk_requires_lon_lat_pair(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main, ["sample-chunk", "--pack", str(tmp_path), "--lon", "-74"]
    )
    assert result.exit_code == 1
    assert "--lon and --lat must be given together" in result.stderr


def test_sample_chunk_requires_origin_pair(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main, ["sample-chunk", "--pack", str(tmp_path), "--x", "64"]
    )
    assert result.exit_code == 1
    assert "--x and --z must be given together" in result.stderr


def test_sample_chunk_rejects_mixed_location_modes(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        ["sample-chunk", "--pack", str(tmp_path),
         "--lon", "-74", "--lat", "40", "--x", "0", "--z", "0"],
    )
    assert result.exit_code == 1
    assert "--lon/--lat or --x/--z" in result.stderr


def test_serve_help_documents_no_browser() -> None:
    result = CliRunner().invoke(main, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--no-browser" in result.stdout


def test_every_command_has_help_text() -> None:
    runner = CliRunner()
    for name in main.commands:
        result = runner.invoke(main, [name, "--help"])
        assert result.exit_code == 0, name
        # Docstring summary must be non-empty and not a bare placeholder.
        assert result.stdout.split("Options:")[0].strip(), name
