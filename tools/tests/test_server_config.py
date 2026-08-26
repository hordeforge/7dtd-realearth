"""Tests for realearth.server_config (shared serverconfig writer for launch scripts)."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from realearth import server_config

ROOT = Path(__file__).resolve().parents[2]
SHIPPED_TEMPLATE = ROOT / "scripts" / "serverconfig_height_test.xml"

TEMPLATE = """<?xml version="1.0"?>
<!-- template rationale -->
<ServerSettings>
\t<property name="GameWorld" value="Navezgane"/>
\t<property name="EACEnabled" value="true"/>
</ServerSettings>
"""


def properties(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {p.get("name", ""): p.get("value", "") for p in root.iterfind("property")}


def write_template(tmp_path: Path, text: str = TEMPLATE) -> Path:
    src = tmp_path / "serverconfig.xml"
    src.write_text(text, encoding="utf-8")
    return src


def test_overrides_existing_and_inserts_missing(tmp_path: Path):
    src = write_template(tmp_path)
    dest = tmp_path / "out" / "live.xml"
    rc = server_config.main([str(src), str(dest), "GameWorld=RealEarth_H500", "ServerVisibility=0"])
    assert rc == 0
    props = properties(dest)
    assert props["GameWorld"] == "RealEarth_H500"
    # A template that drifted and lost the property must still get it, not skip it.
    assert props["ServerVisibility"] == "0"
    assert props["EACEnabled"] == "true"


def test_userdata_is_resolved_absolute(tmp_path: Path):
    src = write_template(tmp_path)
    dest = tmp_path / "live.xml"
    rel = tmp_path / "userdata" / ".." / "userdata"
    server_config.main([str(src), str(dest), "--userdata", str(rel)])
    assert properties(dest)["UserDataFolder"] == str((tmp_path / "userdata").resolve())


def test_quotes_in_values_do_not_escape_the_attribute(tmp_path: Path):
    """A hostile world name is XML-escaped, not spliced into the document."""
    src = write_template(tmp_path)
    dest = tmp_path / "live.xml"
    hostile = 'x"/><property name="EACEnabled" value="false'
    server_config.main([str(src), str(dest), f"GameWorld={hostile}"])
    props = properties(dest)
    assert props["GameWorld"] == hostile
    assert props["EACEnabled"] == "true"


def test_comments_survive(tmp_path: Path):
    src = write_template(tmp_path)
    dest = tmp_path / "live.xml"
    server_config.main([str(src), str(dest), "GameWorld=X"])
    assert "template rationale" in dest.read_text(encoding="utf-8")


def test_shipped_template_round_trips(tmp_path: Path):
    """The template the launch scripts actually read must parse and rewrite."""
    dest = tmp_path / "live.xml"
    server_config.main([str(SHIPPED_TEMPLATE), str(dest), "GameWorld=RealEarth"])
    props = properties(dest)
    assert props["GameWorld"] == "RealEarth"
    assert props["ServerDisabledNetworkProtocols"] == "SteamNetworking"


def test_rejects_wrong_root(tmp_path: Path):
    src = write_template(tmp_path, '<?xml version="1.0"?>\n<Other/>\n')
    with pytest.raises(SystemExit, match="no <ServerSettings>"):
        server_config.main([str(src), str(tmp_path / "live.xml")])


def test_rejects_missing_template(tmp_path: Path):
    with pytest.raises(SystemExit, match="no serverconfig template"):
        server_config.main([str(tmp_path / "nope.xml"), str(tmp_path / "live.xml")])


@pytest.mark.parametrize("pair", ["novalue", "=orphan"])
def test_rejects_malformed_assignment(tmp_path: Path, pair: str):
    src = write_template(tmp_path)
    with pytest.raises(SystemExit, match="NAME=VALUE"):
        server_config.main([str(src), str(tmp_path / "live.xml"), pair])
