#!/usr/bin/env python3
"""Refresh the BuildGuard reviewed-build allowlist.

Hashes the stock + disk-expanded Assembly-CSharp from the local installs and
rewrites the ReviewedBuilds entries in Source/RealEarth/BuildGuard.cs. Run
after verifying a NEW game version (live soak + hook binds green) so the
fail-closed build guard does not block the updated build.

Usage: python3 tools/scripts/refresh_build_guard.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "Source" / "RealEarth" / "BuildGuard.cs"
GAME = Path.home() / ".local/share/Steam/steamapps/common/7 Days To Die"
DEDI = Path.home() / ".local/share/Steam/steamapps/common/7 Days to Die Dedicated Server"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    entries: list[tuple[str, str]] = []
    # Prefer the .re_stock_bak (true stock) over the live DLL (may be expanded).
    managed = "Managed/Assembly-CSharp.dll"
    for label, path in (
        ("V3.2.0 (b9) stock (client bak)", GAME / f"7DaysToDie_Data/{managed}.re_stock_bak"),
        ("V3.2.0 (b9) stock (dedi bak)", DEDI / f"7DaysToDieServer_Data/{managed}.re_stock_bak"),
        ("V3.2.0 (b9) live client", GAME / f"7DaysToDie_Data/{managed}"),
        ("V3.2.0 (b9) live dedi", DEDI / f"7DaysToDieServer_Data/{managed}"),
    ):
        if path.is_file():
            entries.append((sha256(path), label))
    if not entries:
        print("no Assembly-CSharp found; nothing to refresh", file=sys.stderr)
        return 1

    src = GUARD.read_text(encoding="utf-8")
    start = src.index("ReviewedBuilds =")
    end = src.index("};", start) + 2
    body = "\n".join(f'                {{"{h}", "{label}"}},' for h, label in entries)
    new_block = (
        "ReviewedBuilds =\n"
        "            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)\n"
        "            {\n" + body + "\n            };"
    )
    src = src[:start] + new_block + src[end:]
    GUARD.write_text(src, encoding="utf-8")
    print(f"refreshed {len(entries)} reviewed build(s) in {GUARD.name}:")
    for h, label in entries:
        print(f"  {h[:16]}... {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
