"""Targeted height-mod test case (drives realearth.height_mod_case)."""

from realearth.height_mod_case import all_passed, format_report, run_height_mod_case


def test_height_mod_case_all_pass():
    results = run_height_mod_case()
    assert all_passed(results), format_report(results)


def test_height_mod_case_has_everest_and_fly_checks():
    names = {r.name for r in run_height_mod_case()}
    assert "everest_summit" in names
    assert "fly_over_everest" in names
    assert "fly_headroom_blocks" in names
    assert "ceiling_constants" in names
