"""Pin scripts/useroptions_ini.sh: the dedicated launcher's UserOptions rewrite.

scripts/start_dedicated_minimal.sh runs on every server start, so the setter it
calls is executed as many times as the server is restarted. Appending the key
made each start add another copy of it, growing the file and leaving the
effective value dependent on the start count. These tests drive the shipped
script on synthetic files and assert the run-twice result is byte-identical to
the run-once result.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "useroptions_ini.sh"

EXISTING = """[General]
PlayerName=Server
  discorddisabled = false
ResolutionWidth=1920
[Other]
DiscordDisabled=true
"""


def apply_key(path: Path, pair: str = "DiscordDisabled=true") -> str:
    subprocess.run(["bash", str(SCRIPT), str(path), pair], check=True)
    return path.read_text(encoding="utf-8")


def test_second_run_changes_nothing(tmp_path) -> None:
    """One run on an existing file already carries the file to its fixed point."""
    path = tmp_path / "UserOptions.ini"
    path.write_text(EXISTING, encoding="utf-8")

    after_one = apply_key(path)
    after_two = apply_key(path)

    assert after_one == after_two
    # Every pre-existing copy of the key is gone, whatever its case, spacing
    # or section, and exactly one survives under [General].
    assert after_one.count("DiscordDisabled=true") == 1
    assert after_one == (
        "[General]\n"
        "DiscordDisabled=true\n"
        "PlayerName=Server\n"
        "ResolutionWidth=1920\n"
        "[Other]\n"
    )


def test_missing_file_is_created_once(tmp_path) -> None:
    path = tmp_path / "UserOptions.ini"

    first = apply_key(path)
    second = apply_key(path)

    assert first == "[General]\nDiscordDisabled=true\n"
    assert first == second


def test_other_keys_and_sections_survive(tmp_path) -> None:
    path = tmp_path / "UserOptions.ini"
    path.write_text("[General]\nPlayerName=Server\n", encoding="utf-8")

    assert apply_key(path) == "[General]\nDiscordDisabled=true\nPlayerName=Server\n"


def test_scratch_file_is_not_left_behind(tmp_path) -> None:
    path = tmp_path / "UserOptions.ini"
    path.write_text(EXISTING, encoding="utf-8")

    apply_key(path)

    assert [p.name for p in tmp_path.iterdir()] == ["UserOptions.ini"]


def test_bad_assignment_is_rejected(tmp_path) -> None:
    path = tmp_path / "UserOptions.ini"
    path.write_text(EXISTING, encoding="utf-8")

    result = subprocess.run(
        ["bash", str(SCRIPT), str(path), "DiscordDisabled"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert path.read_text(encoding="utf-8") == EXISTING
