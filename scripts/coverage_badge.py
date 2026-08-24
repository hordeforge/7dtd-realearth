#!/usr/bin/env python3
"""Render the line-coverage badge SVG from the local .coverage file.

Must be run by an interpreter that has coverage importable: the Makefile
`coverage` target arranges that (`--with coverage` under uv, the dev
dependency group otherwise). Usage: coverage_badge.py OUTPUT.svg
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def percentage() -> int:
    out = Path(".coverage.json")
    subprocess.run(
        [sys.executable, "-m", "coverage", "json", "-q", "-o", str(out)],
        check=True,
    )
    data = json.loads(out.read_text())
    out.unlink()
    totals = data["totals"]
    return round(float(totals["percent_covered"]))


def colour(pct: int) -> str:
    if pct >= 90:
        return "#4c1"
    if pct >= 75:
        return "#97ca00"
    if pct >= 60:
        return "#dfb317"
    if pct >= 40:
        return "#fe7d37"
    return "#e05d44"


def badge(pct: int, fill: str) -> str:
    label_w, value_w = 64, 36
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{label_w + value_w}" height="20" role="img" aria-label="coverage: {pct}%">
<title>coverage: {pct}%</title>
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="{label_w + value_w}" height="20" rx="3" fill="#fff"/></clipPath>
<g clip-path="url(#r)"><rect width="{label_w}" height="20" fill="#555"/><rect x="{label_w}" width="{value_w}" height="20" fill="{fill}"/><rect width="{label_w + value_w}" height="20" fill="url(#s)"/></g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11"><text x="{label_w / 2}" y="14">coverage</text><text x="{label_w + value_w / 2}" y="14">{pct}%</text></g>
</svg>
"""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: coverage_badge.py OUTPUT.svg", file=sys.stderr)
        return 2
    pct = percentage()
    Path(argv[1]).write_text(badge(pct, colour(pct)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
