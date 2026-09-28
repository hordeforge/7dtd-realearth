"""CLI contract tests: exit codes, clean errors, help consistency."""

import json
import re
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
    assert _safe_name_component({"name": "RealEarth_H500"}, "name", "Fallback") == "RealEarth_H500"
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
    (pack / "height_test.json").write_text(json.dumps({"name": "../../victim"}), encoding="utf-8")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("x", encoding="utf-8")
    from realearth.cli import _install_height_test

    with pytest.raises(ValueError, match="plain directory name"):
        _install_height_test(tmp_path, pack, tmp_path / "world")
    assert (victim / "keep.txt").is_file()


def test_install_height_test_honors_sevendtd_game_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mod install target follows SEVENDTD_GAME_DIR like every script."""
    game = tmp_path / "game"
    mod = game / "Mods" / "RealEarth"
    (mod / "Config").mkdir(parents=True)
    (mod / "Config" / "realearth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SEVENDTD_GAME_DIR", str(game))
    monkeypatch.setattr(
        "realearth.proton_paths.client_generated_worlds_targets",
        lambda **_kw: [tmp_path / "GeneratedWorlds"],
    )
    pack = tmp_path / "pack"
    (pack / "tiles").mkdir(parents=True)
    (pack / "tiles" / "tile.rte").write_bytes(b"RTE1")
    (pack / "earth.manifest.json").write_text(
        json.dumps({"world_width": 512, "world_height": 512, "tile_size": 512}),
        encoding="utf-8",
    )
    world = tmp_path / "world"
    world.mkdir()
    from realearth.cli import _install_height_test

    _install_height_test(tmp_path, pack, world)
    assert (mod / "Data" / "tiles" / "tiles" / "tile.rte").is_file()
    cfg = json.loads((mod / "Config" / "realearth.json").read_text(encoding="utf-8"))
    assert cfg["MapMode"] == "Streamed"
    assert (tmp_path / "GeneratedWorlds" / "RealEarth_HeightTest").is_dir()


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
        [
            "planet-tiles",
            "--west",
            "-105.3",
            "--south",
            "39.5",
            "--east",
            "-104.7",
            "--north",
            "40.0",
        ],
    )
    assert result.exit_code == 0
    # stdout is pure data ("tx tz" pairs); the count line lives on stderr so
    # scripts can pipe stdout straight into a read loop.
    match = re.search(r"^(\d+) tiles$", result.stderr, flags=re.MULTILINE)
    assert match
    assert int(match.group(1)) >= len(result.stdout.splitlines())
    for line in result.stdout.splitlines():
        tx, tz = line.split()
        int(tx)
        int(tz)


def test_planet_tiles_rejects_north_le_south() -> None:
    result = CliRunner().invoke(
        main,
        [
            "planet-tiles",
            "--west",
            "10",
            "--south",
            "50",
            "--east",
            "20",
            "--north",
            "40",
        ],
    )
    assert result.exit_code == 2
    assert "north>south" in result.stderr
    assert "Traceback" not in result.stderr


def test_planet_tiles_accepts_dateline_west_gt_east() -> None:
    """Pacific west>east bbox splits; planner must succeed without hang."""
    result = CliRunner().invoke(
        main,
        [
            "planet-tiles",
            "--west",
            "170",
            "--south",
            "-5",
            "--east",
            "-170",
            "--north",
            "5",
        ],
    )
    assert result.exit_code == 0
    assert "Traceback" not in result.stderr
    match = re.search(r"^(\d+) tiles$", result.stderr, flags=re.MULTILINE)
    assert match
    assert int(match.group(1)) >= 1
    for line in result.stdout.splitlines():
        tx, tz = line.split()
        int(tx)
        int(tz)


@pytest.mark.parametrize("flag", ["west", "south", "east", "north"])
def test_planet_tiles_rejects_non_finite_bbox(flag: str) -> None:
    kwargs = {"--west": "-105.3", "--south": "39.5", "--east": "-104.7", "--north": "40.0"}
    kwargs[f"--{flag}"] = "nan"
    args = [arg for name, value in kwargs.items() for arg in (name, value)]
    result = CliRunner().invoke(main, ["planet-tiles", *args])
    assert result.exit_code == 2
    assert "Traceback" not in result.stderr
    assert flag in result.stderr.lower()


def test_build_region_rejects_inverted_bbox(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(
        main,
        [
            "build-region",
            "--west",
            "10",
            "--south",
            "50",
            "--east",
            "5",
            "--north",
            "40",
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code == 2
    assert "Traceback" not in result.stderr
    assert "east>west" in result.stderr
    # Validation must fire before any build work touches disk.
    assert not out_dir.exists()


@pytest.mark.parametrize("bad", ["inf", "-inf", "nan"])
def test_planet_tiles_rejects_each_non_finite_form(bad: str) -> None:
    """Non-finite bbox floats must be a usage error, not a deep ValueError."""
    result = CliRunner().invoke(
        main,
        ["planet-tiles", "--west", bad, "--south", "0", "--east", "1", "--north", "1"],
    )
    assert result.exit_code == 2
    assert "Traceback" not in result.stderr
    assert "--west" in result.stderr


def test_build_region_rejects_inverted_and_non_finite_bbox(tmp_path: Path) -> None:
    runner = CliRunner()
    inverted = runner.invoke(
        main,
        [
            "build-region",
            "--west",
            "10",
            "--east",
            "5",
            "--south",
            "0",
            "--north",
            "1",
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert inverted.exit_code == 2
    assert "east>west" in inverted.stderr
    non_finite = runner.invoke(
        main,
        [
            "build-region",
            "--north",
            "nan",
            "--west",
            "0",
            "--south",
            "0",
            "--east",
            "1",
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert non_finite.exit_code == 2
    assert "Traceback" not in non_finite.stderr
    assert "finite" in non_finite.stderr


def test_sample_chunk_requires_lon_lat_pair(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["sample-chunk", "--pack", str(tmp_path), "--lon", "-74"])
    assert result.exit_code == 2
    assert "--lon and --lat must be given together" in result.stderr


def test_sample_chunk_requires_origin_pair(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["sample-chunk", "--pack", str(tmp_path), "--x", "64"])
    assert result.exit_code == 2
    assert "--x and --z must be given together" in result.stderr


def test_sample_chunk_rejects_mixed_location_modes(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        [
            "sample-chunk",
            "--pack",
            str(tmp_path),
            "--lon",
            "-74",
            "--lat",
            "40",
            "--x",
            "0",
            "--z",
            "0",
        ],
    )
    assert result.exit_code == 2
    assert "--lon/--lat or --x/--z" in result.stderr


def test_serve_help_documents_no_browser() -> None:
    result = CliRunner().invoke(main, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--no-browser" in result.stdout


def test_key_options_document_their_meaning() -> None:
    """Options beyond bare defaults must say what they do."""
    build = CliRunner().invoke(main, ["build-region", "--help"]).stdout
    assert "Tile edge in blocks" in build
    assert "Region name" in build
    serve = CliRunner().invoke(main, ["serve", "--help"]).stdout
    assert "TCP port" in serve
    assert "Address to bind" in serve


def test_every_command_has_help_text() -> None:
    runner = CliRunner()
    for name in main.commands:
        result = runner.invoke(main, [name, "--help"])
        assert result.exit_code == 0, name
        # Docstring summary must be non-empty and not a bare placeholder.
        assert result.stdout.split("Options:")[0].strip(), name


def test_short_help_flag_is_available_everywhere() -> None:
    """-h answers on the group and on every subcommand, argparse CLIs included."""
    runner = CliRunner()
    assert runner.invoke(main, ["-h"]).exit_code == 0
    # lonlat/wrap-check override context_settings to keep negative positionals;
    # the -h alias must survive that override.
    for name in main.commands:
        assert runner.invoke(main, [name, "-h"]).exit_code == 0, name


def test_corrupt_manifest_is_a_clean_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["list-tiles", str(tmp_path)])
    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    (tmp_path / "earth.manifest.json").write_text("not json", encoding="utf-8")
    corrupt = CliRunner().invoke(main, ["list-tiles", str(tmp_path)])
    assert corrupt.exit_code == 1
    assert "Traceback" not in corrupt.stderr
    assert "not valid JSON" in corrupt.stderr
    assert "earth.manifest.json" in corrupt.stderr


def test_verify_build_reports_bad_json_without_traceback(tmp_path: Path) -> None:
    (tmp_path / "build.json").write_text("{oops", encoding="utf-8")
    result = CliRunner().invoke(main, ["verify-build", "--pack", str(tmp_path)])
    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    assert "build.json" in result.stderr


def test_verify_build_rejects_input_without_file_field(tmp_path: Path) -> None:
    (tmp_path / "build.json").write_text(
        json.dumps({"schema": "realearth.build.v1", "inputs": {"dem": {}}}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(main, ["verify-build", "--pack", str(tmp_path)])
    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    assert "dem" in result.stderr


@pytest.mark.parametrize(
    "tail_argv",
    [
        ["bake-world", "--out", "{out}"],
        ["export-viewer", "--out", "{out}"],
        ["sample-chunk"],
    ],
)
def test_pack_commands_reject_a_directory_without_a_manifest(
    tmp_path: Path, tail_argv: list[str]
) -> None:
    """A wrong --pack must name the missing file, not traceback or fake a pack.

    An empty --pack used to reach the reader (FileNotFoundError traceback) or,
    for sample-chunk, decode nothing and print a flat all-sea chunk as if it
    were real sample data.
    """
    command, rest = tail_argv[0], tail_argv[1:]
    args = [command, "--pack", str(tmp_path), *[a.format(out=str(tmp_path / "w")) for a in rest]]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    assert "earth.manifest.json" in result.stderr


def test_planet_tiles_limit_zero_prints_every_tile() -> None:
    """The default 50-line cap would silently drop tiles from a pipe."""
    runner = CliRunner()
    base = ["planet-tiles", "--west", "-1", "--south", "-1", "--east", "1", "--north", "1"]
    capped = runner.invoke(main, base)
    assert capped.exit_code == 0
    full = runner.invoke(main, [*base, "--limit", "0"])
    assert full.exit_code == 0
    assert len(full.stdout.splitlines()) > len(capped.stdout.splitlines())
    assert "... and" in capped.stderr
    assert "... and" not in full.stderr


def test_planet_tiles_rejects_a_negative_limit() -> None:
    result = CliRunner().invoke(
        main,
        [
            "planet-tiles",
            "--west",
            "-1",
            "--south",
            "-1",
            "--east",
            "1",
            "--north",
            "1",
            "--limit",
            "-1",
        ],
    )
    assert result.exit_code == 2
    assert "--limit" in result.stderr
