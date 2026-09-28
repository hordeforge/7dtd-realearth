"""The install scripts must publish a mod over the live one, never over a hole.

scripts/atomic_dir_swap.sh is the mechanism: fill a sibling staging dir, then
swap it onto the destination with renames. These tests run it for real, because
the failure they guard against (a Mods/RealEarth that is empty or half-copied
when an install dies) is invisible in a source grep.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "atomic_dir_swap.sh"


WORLD_HELPER = ROOT / "scripts" / "generated-world.sh"


def _bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'set -euo pipefail\nsource "{HELPER}"\n{script}'],
        capture_output=True,
        text=True,
        check=True,
    )


def _leftovers(parent: Path, name: str) -> list[Path]:
    return sorted(p.name for p in parent.iterdir() if name in p.name)


def test_publish_replaces_live_content_and_leaves_no_debris(tmp_path: Path) -> None:
    dest = tmp_path / "Mods" / "RealEarth"
    dest.mkdir(parents=True)
    (dest / "old.dll").write_text("stale", encoding="utf-8")

    _bash(f"""
        atomic_swap_begin "{dest}"
        echo fresh > "$RE_ATOMIC_STAGING/RealEarth.dll"
        atomic_swap_publish "{dest}"
        """)

    assert not (dest / "old.dll").exists()
    assert (dest / "RealEarth.dll").read_text(encoding="utf-8") == "fresh\n"
    assert _leftovers(tmp_path / "Mods", "RealEarth") == ["RealEarth"]


def test_failed_fill_leaves_the_previous_install_intact(tmp_path: Path) -> None:
    dest = tmp_path / "Mods" / "RealEarth"
    dest.mkdir(parents=True)
    (dest / "RealEarth.dll").write_text("working", encoding="utf-8")

    # What an interrupted install does: start staging, write part of the tree,
    # then die. atomic_swap_cleanup is the EXIT trap the install scripts set.
    _bash(f"""
        atomic_swap_begin "{dest}"
        echo partial > "$RE_ATOMIC_STAGING/RealEarth.dll"
        atomic_swap_cleanup
        """)

    assert (dest / "RealEarth.dll").read_text(encoding="utf-8") == "working"
    assert _leftovers(tmp_path / "Mods", "RealEarth") == ["RealEarth"]


def test_publish_without_begin_is_refused(tmp_path: Path) -> None:
    dest = tmp_path / "Mods" / "RealEarth"
    dest.mkdir(parents=True)
    (dest / "RealEarth.dll").write_text("working", encoding="utf-8")

    result = subprocess.run(
        ["bash", "-c", f'source "{HELPER}"\natomic_swap_publish "{dest}"'],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "atomic_swap_begin" in result.stderr
    assert (dest / "RealEarth.dll").read_text(encoding="utf-8") == "working"


def test_install_script_publishes_instead_of_deleting_the_live_folder() -> None:
    """install_proton.sh must not rm -rf the mod or world it is replacing.

    The mod goes through the rename swap; the generated world goes through
    install_generated_world, which moves the previous world into
    GeneratedWorlds_trash instead of deleting it (a GeneratedWorlds entry can
    hold state no backup archive covers).
    """
    src = (ROOT / "scripts" / "install_proton.sh").read_text(encoding="utf-8")
    assert 'source "$ROOT/scripts/atomic_dir_swap.sh"' in src
    assert 'rm -rf "$dest"' not in src
    assert "trap atomic_swap_cleanup EXIT" in src
    # The mod is published through the swap. The generated world is not: it goes
    # through install_generated_world, which moves the live world into
    # GeneratedWorlds_trash because the atomic swap drops the previous copy, and
    # a world can carry hand-edited state no backup holds.
    assert 'source "$ROOT/scripts/generated-world.sh"' in src
    assert src.count("atomic_swap_publish") == 1
    assert 'install_generated_world "$WORLD_SRC"' in src
    world_helper = (ROOT / "scripts" / "generated-world.sh").read_text(encoding="utf-8")
    assert "move_aside" in world_helper
    code = [line for line in world_helper.splitlines() if not line.lstrip().startswith("#")]
    # The one deletion allowed is the retention prune on the helper's own trash
    # entries, which is what keeps a repeated install from filling the disk.
    # Everything else must keep the world it replaces.
    prune = [line for line in code if "-mtime" in line or "_TRASH_DAYS" in line]
    code = [line for line in code if line not in prune]
    assert not [
        line for line in code if "rm -rf" in line
    ], "install_generated_world must keep the world it replaces, never delete it"


def test_generated_world_install_keeps_the_replaced_world(tmp_path: Path) -> None:
    """install_generated_world moves the live world aside into a trash dir.

    Overwriting in place would be an unrecoverable delete: a GeneratedWorlds
    entry carries hand-edited or differently generated state that no archive in
    backups/ holds.
    """
    src = tmp_path / "worlds" / "RealEarth"
    src.mkdir(parents=True)
    (src / "dtm.raw").write_text("new", encoding="utf-8")

    userdata = tmp_path / "userdata"
    gw = userdata / "GeneratedWorlds"
    live = gw / "RealEarth"
    live.mkdir(parents=True)
    (live / "dtm.raw").write_text("live", encoding="utf-8")
    (live / "hand-edited.txt").write_text("keep me", encoding="utf-8")

    _bash(f'source "{WORLD_HELPER}"\ninstall_generated_world "{src}" "{gw}" RealEarth')

    assert (live / "dtm.raw").read_text(encoding="utf-8") == "new"
    assert not (live / "hand-edited.txt").exists()

    trash = userdata / "GeneratedWorlds_trash"
    kept = [p for p in trash.iterdir() if p.name.endswith("__RealEarth")]
    assert len(kept) == 1, kept
    assert (kept[0] / "dtm.raw").read_text(encoding="utf-8") == "live"
    assert (kept[0] / "hand-edited.txt").read_text(encoding="utf-8") == "keep me"
    # The trash dir is a sibling of GeneratedWorlds, so the game does not offer
    # the kept world as a selectable entry.
    assert sorted(p.name for p in gw.iterdir()) == ["RealEarth"]


def test_generated_world_install_without_previous_world(tmp_path: Path) -> None:
    """First install has nothing to move aside and must not create a trash dir."""
    src = tmp_path / "worlds" / "RealEarth"
    src.mkdir(parents=True)
    (src / "dtm.raw").write_text("new", encoding="utf-8")
    gw = tmp_path / "userdata" / "GeneratedWorlds"

    _bash(f'source "{WORLD_HELPER}"\ninstall_generated_world "{src}" "{gw}" RealEarth')

    assert (gw / "RealEarth" / "dtm.raw").read_text(encoding="utf-8") == "new"
    assert not (tmp_path / "userdata" / "GeneratedWorlds_trash").exists()


def test_generated_world_reinstall_is_a_fixed_point(tmp_path: Path) -> None:
    """Installing the same world twice changes nothing the second time.

    Every install script calls install_generated_world for each target, and a
    rerun used to copy the whole world again and park a second full copy in
    GeneratedWorlds_trash, so repeating an install grew the disk without
    replacing anything.
    """
    src = tmp_path / "worlds" / "RealEarth"
    (src / "nested").mkdir(parents=True)
    (src / "dtm.raw").write_text("payload", encoding="utf-8")
    (src / "nested" / "main.ttw").write_text("ttw", encoding="utf-8")
    gw = tmp_path / "userdata" / "GeneratedWorlds"

    _bash(f'source "{WORLD_HELPER}"\ninstall_generated_world "{src}" "{gw}" RealEarth')
    _bash(f'source "{WORLD_HELPER}"\ninstall_generated_world "{src}" "{gw}" RealEarth')

    assert (gw / "RealEarth" / "dtm.raw").read_text(encoding="utf-8") == "payload"
    assert (gw / "RealEarth" / "nested" / "main.ttw").exists()
    assert not (tmp_path / "userdata" / "GeneratedWorlds_trash").exists()


def test_generated_world_reinstall_after_source_change_replaces_it(tmp_path: Path) -> None:
    """A changed source still replaces the live world, and the old one is kept."""
    src = tmp_path / "worlds" / "RealEarth"
    src.mkdir(parents=True)
    (src / "dtm.raw").write_text("first", encoding="utf-8")
    gw = tmp_path / "userdata" / "GeneratedWorlds"

    _bash(f'source "{WORLD_HELPER}"\ninstall_generated_world "{src}" "{gw}" RealEarth')
    (src / "dtm.raw").write_text("second", encoding="utf-8")
    _bash(f'source "{WORLD_HELPER}"\ninstall_generated_world "{src}" "{gw}" RealEarth')

    assert (gw / "RealEarth" / "dtm.raw").read_text(encoding="utf-8") == "second"
    trash = tmp_path / "userdata" / "GeneratedWorlds_trash"
    kept = [p for p in trash.iterdir() if p.name.endswith("__RealEarth")]
    assert len(kept) == 1, kept
    assert (kept[0] / "dtm.raw").read_text(encoding="utf-8") == "first"


def test_generated_world_reinstall_after_game_edited_the_world(tmp_path: Path) -> None:
    """State the game added to the installed world is not mistaken for current.

    The current-check compares path, size and mtime, so a file the server
    wrote into GeneratedWorlds/RealEarth (or a changed one) makes the next
    install replace the tree instead of skipping it.
    """
    src = tmp_path / "worlds" / "RealEarth"
    src.mkdir(parents=True)
    (src / "dtm.raw").write_text("payload", encoding="utf-8")
    gw = tmp_path / "userdata" / "GeneratedWorlds"

    _bash(f'source "{WORLD_HELPER}"\ninstall_generated_world "{src}" "{gw}" RealEarth')
    (gw / "RealEarth" / "player.tmp").write_text("half-written world", encoding="utf-8")
    _bash(f'source "{WORLD_HELPER}"\ninstall_generated_world "{src}" "{gw}" RealEarth')

    assert not (gw / "RealEarth" / "player.tmp").exists()
    assert (gw / "RealEarth" / "dtm.raw").exists()
    trash = tmp_path / "userdata" / "GeneratedWorlds_trash"
    assert [p for p in trash.iterdir() if p.name.endswith("__RealEarth")]


def test_generated_world_trash_is_pruned_and_never_kept_forever(tmp_path: Path) -> None:
    """The moved-aside copies do not accumulate without bound."""
    src = tmp_path / "worlds" / "RealEarth"
    src.mkdir(parents=True)
    (src / "dtm.raw").write_text("payload", encoding="utf-8")
    gw = tmp_path / "userdata" / "GeneratedWorlds"

    _bash(
        f'export RE_WORLD_TRASH_DAYS=7\nsource "{WORLD_HELPER}"\n'
        f'install_generated_world "{src}" "{gw}" RealEarth'
    )
    trash = tmp_path / "userdata" / "GeneratedWorlds_trash"
    # An entry older than the window, as a bake from last month would leave.
    stale = trash / "2020-01-01__00-00-00__RealEarth"
    stale.mkdir(parents=True)
    (stale / "dtm.raw").write_text("ancient", encoding="utf-8")
    (src / "dtm.raw").write_text("newer", encoding="utf-8")
    subprocess.run(
        ["touch", "-d", "30 days ago", str(stale)],
        check=True,
        capture_output=True,
    )

    _bash(
        f'export RE_WORLD_TRASH_DAYS=7\nsource "{WORLD_HELPER}"\n'
        f'install_generated_world "{src}" "{gw}" RealEarth'
    )

    assert not stale.exists()
    # The world replaced on this run is still there.
    fresh = [p for p in trash.iterdir() if p.name.endswith("__RealEarth")]
    assert len(fresh) == 1, fresh
    assert (fresh[0] / "dtm.raw").read_text(encoding="utf-8") == "payload"


def test_generated_world_bad_trash_window_is_refused(tmp_path: Path) -> None:
    """A non-numeric retention window fails the install instead of never pruning."""
    src = tmp_path / "worlds" / "RealEarth"
    src.mkdir(parents=True)
    (src / "dtm.raw").write_text("payload", encoding="utf-8")
    gw = tmp_path / "userdata" / "GeneratedWorlds"

    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                "set -euo pipefail\nexport RE_WORLD_TRASH_DAYS=soon\n"
                f'source "{WORLD_HELPER}"\n'
                f'install_generated_world "{src}" "{gw}" RealEarth'
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "RE_WORLD_TRASH_DAYS" in result.stderr
