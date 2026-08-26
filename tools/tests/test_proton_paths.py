"""Drive shipped proton_paths resolution against real Steam layout when present."""

from pathlib import Path

from realearth.proton_paths import (
    DEFAULT_CLIENT_GAME_DIR,
    STEAM_APPID,
    client_game_dir,
    client_generated_worlds_targets,
    native_linux_userdata,
    primary_client_userdata,
    proton_userdata,
)


def test_client_game_dir_honors_sevendtd_game_dir(monkeypatch) -> None:
    """SEVENDTD_GAME_DIR is the project-wide override (Makefile, scripts, csproj)."""
    monkeypatch.delenv("SEVENDTD_GAME_DIR", raising=False)
    assert client_game_dir() == DEFAULT_CLIENT_GAME_DIR
    monkeypatch.setenv("SEVENDTD_GAME_DIR", "/somewhere/else/7 Days To Die")
    assert client_game_dir() == Path("/somewhere/else/7 Days To Die")


def test_default_game_dll_follows_sevendtd_game_dir(monkeypatch) -> None:
    from realearth.engine_constants import default_game_dll

    monkeypatch.setenv("SEVENDTD_GAME_DIR", "/opt/game")
    dll = default_game_dll()
    assert "7DaysToDie_Data" in dll.parts
    assert dll.name == "Assembly-CSharp.dll"


def test_native_linux_userdata_is_under_home():
    p = native_linux_userdata()
    assert p.name == "7DaysToDie"
    assert "7DaysToDie" in str(p)


def test_primary_client_prefers_proton_when_compatdata_exists():
    proton = proton_userdata(STEAM_APPID)
    primary = primary_client_userdata()
    if proton is not None:
        # Real Steam/Proton install on this machine
        assert primary == proton
        assert "compatdata" in str(primary)
        assert "AppData/Roaming/7DaysToDie" in str(primary).replace("\\", "/")
        assert primary.is_dir()
    else:
        assert primary == native_linux_userdata()


def test_generated_worlds_targets_include_proton_roaming_on_this_machine():
    targets = client_generated_worlds_targets(prefer_proton=True, also_native=True)
    assert len(targets) >= 1
    proton = proton_userdata()
    if proton is not None:
        expected = proton / "GeneratedWorlds"
        assert expected in targets
        # Must not be ONLY native path when Proton exists
        assert any("compatdata" in str(t) for t in targets)
