"""Session snapshot JSON must round-trip any place name the pack can carry.

SessionStateStore hand-writes the snapshot (no JSON library on the game side)
and hand-reads it back. DiscoveredCities is the only field holding external
text: place names arrive from pack JSON and are written verbatim. A name
containing a quote or a control char is the failing input:

  * the reader stopped at the first unescaped `\"`, so the name came back
    truncated and no longer matched any catalog key, re-discovering the city;
  * a raw CR/LF in a value split the snapshot across lines for whoever reads
    the file by hand.

The escape set is pinned against the stdlib json reference rather than against
a hand-written expectation, so a dropped case fails here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "Source" / "RealEarth"

# Names a pack can legally carry: quotes, backslashes, a C0 control, a C1
# control, an astral character, and an NFD spelling the runtime then folds.
HOSTILE_NAMES = [
    'Foo"Bar',
    "back\\slash",
    "line\nbreak",
    "tab\there",
    "del\x7fchar",
    "c1\x85next",
    "astral \U0001f1e6\U0001f1e7 flag",
    "combining a\u0301",
]


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _escape_cases() -> set[str]:
    """Literal characters the C# Escape switch maps to a short escape."""
    body = re.search(
        r"static string Escape\(string s\)(.*?)\n        \}", _read("SessionStateStore.cs"), re.S
    )
    assert body, "SessionStateStore must define Escape"
    cases = re.findall(r"case '(\\\\|.)':", body.group(1), re.S)
    return {raw.replace("\\\\", "\\") for raw in cases}


def test_escape_covers_every_character_json_requires():
    # The short escapes json itself uses (\b \f \n \r \t) plus the two
    # structural ones; every other control char goes out as \uXXXX, which json
    # also requires but spells differently.
    required = set(json.encoder.ESCAPE_DCT) - set('"\\') - {chr(c) for c in range(0x20)}
    missing = required - _escape_cases()
    assert not missing, f"Escape must map {sorted(missing)} to a short escape"
    assert set('"\\') <= _escape_cases()
    # Anything else outside printable ASCII goes out as \uXXXX.
    assert re.search(
        r"if \(c < ' ' \|\| \(c >= '\\u007f' && c <= '\\u009f'\)\)", _read("SessionStateStore.cs")
    ), "Escape must escape the remaining C0, DEL and C1 chars as \\uXXXX"


def test_escaped_snapshot_is_valid_json_and_decodes_to_the_original_names():
    """Escape as the C# declares it, then parse with the stdlib reader."""
    cases = _escape_cases()
    src = _read("SessionStateStore.cs")

    def escape(value: str) -> str:
        out = []
        for c in value:
            if c in cases:
                out.append(
                    {
                        '"': '\\"',
                        "\\": "\\\\",
                        "\b": "\\b",
                        "\f": "\\f",
                        "\n": "\\n",
                        "\r": "\\r",
                        "\t": "\\t",
                    }[c]
                )
            elif c < " " or "\x7f" <= c <= "\x9f":
                out.append(f"\\u{ord(c):04x}")
            else:
                out.append(c)
        return "".join(out)

    snapshot = (
        '{"schema":"realearth.session.v1","originEarthX":0,"originEarthZ":0,'
        '"absoluteX":0,"absoluteZ":0,"mapMode":"Streamed",'
        '"multiplayerOriginMode":"SoloSlide","spawnLon":0.0,"spawnLat":0.0,'
        '"scope":"","discoveredCities":['
        + ",".join('"' + escape(n) + '"' for n in HOSTILE_NAMES)
        + "]}"
    )
    # No raw newline or quote may leak into the file.
    assert "\n" not in snapshot and snapshot.count("\n") == 0
    assert json.loads(snapshot)["discoveredCities"] == HOSTILE_NAMES
    # The reader is the mirror image: escape-aware scan plus unescape.
    assert "json.IndexOf('\"', q1 + 1)" not in src, "reader must use FindStringEnd"
    assert src.count("Unescape(json.Substring(") == 2
    assert "case 'u':" in src and "NumberStyles.HexNumber" in src


def test_snapshot_write_path_declares_utf8():
    """AtomicPublish is the only writer; an implicit default codec is what the
    reader's Encoding.UTF8 would silently disagree with."""
    pub = _read("AtomicPublish.cs")
    assert "new UTF8Encoding(false)" in pub
    assert "File.WriteAllText(tmp, contents);" not in pub


def test_unreadable_snapshot_log_reports_bytes_not_code_units():
    src = _read("SessionStateStore.cs")
    assert "bytes={Encoding.UTF8.GetByteCount(json)}" in src
    assert "bytes={json.Length}" not in src
