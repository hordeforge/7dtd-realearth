"""Drive shipped proton_paths resolution against real Steam layout when present."""


from realearth.proton_paths import (
    STEAM_APPID,
    client_generated_worlds_targets,
    native_linux_userdata,
    primary_client_userdata,
    proton_userdata,
)


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
