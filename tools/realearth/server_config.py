#!/usr/bin/env python3
"""Write a 7DTD dedicated serverconfig.xml with properties overridden.

Single source for what the dedicated launch scripts used to embed as inline
python heredocs (start_dedicated_minimal.sh, start_dedicated_prefab.sh,
run_dedicated_height_test.sh). Values arrive as argv, never spliced into a
script body, and a property the template does not carry is inserted rather
than silently skipped, so a drifting template cannot quietly drop
`EACEnabled` or `ServerVisibility`.

Stdlib only so it runs where uv does not:
  PYTHONPATH=tools python3 -m realearth.server_config SRC DEST \
      [--userdata PATH] [NAME=VALUE ...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

# Serverconfig is tab-indented under a single <ServerSettings> root; inserted
# properties match that so a written file still diffs cleanly against a template.
INDENT = "\t"


def split_prolog(text: str) -> tuple[str, str]:
    """Split SRC text at <ServerSettings>. ElementTree drops everything before the
    root, and the templates carry their rationale in a comment block there."""
    start = text.find("<ServerSettings")
    if start < 0:
        raise SystemExit("ERROR: no <ServerSettings> root element")
    return text[:start], text[start:]


def set_property(root: ET.Element, name: str, value: str) -> bool:
    """Set <property name=... value=...>. Returns True when newly inserted."""
    for prop in root.iterfind("property"):
        if prop.get("name") == name:
            prop.set("value", value)
            return False
    inserted = ET.SubElement(root, "property")
    inserted.set("name", name)
    inserted.set("value", value)
    inserted.tail = "\n" + INDENT
    return True


def write_config(src: Path, dest: Path, properties: dict[str, str]) -> list[str]:
    """Apply `properties` to the SRC template and write DEST. Returns a summary."""
    prolog, body = split_prolog(src.read_text(encoding="utf-8"))
    # insert_comments keeps the per-property comments inside the root.
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    parser.feed(body)
    root = parser.close()

    summary = []
    for name, value in properties.items():
        inserted = set_property(root, name, value)
        summary.append(f"{name}={value}{' (inserted)' if inserted else ''}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        prolog + ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8"
    )
    return summary


def parse_assignment(pair: str) -> tuple[str, str]:
    name, sep, value = pair.partition("=")
    if not sep or not name:
        raise SystemExit(f"ERROR: property must be NAME=VALUE, got: {pair!r}")
    return name, value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src", type=Path, help="serverconfig template to read")
    parser.add_argument("dest", type=Path, help="serverconfig to write")
    parser.add_argument(
        "--userdata",
        type=Path,
        help="set UserDataFolder to this path, resolved to an absolute path",
    )
    parser.add_argument("properties", nargs="*", metavar="NAME=VALUE")
    args = parser.parse_args(argv)

    if not args.src.is_file():
        raise SystemExit(f"ERROR: no serverconfig template at {args.src}")

    properties: dict[str, str] = {}
    if args.userdata is not None:
        properties["UserDataFolder"] = str(args.userdata.resolve())
    properties.update(parse_assignment(p) for p in args.properties)

    summary = write_config(args.src, args.dest, properties)
    print(f"config -> {args.dest}")
    for line in summary:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
