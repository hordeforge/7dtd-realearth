#!/usr/bin/env python3
"""Refresh the BuildGuard reviewed-build allowlist.

Hashes the stock + disk-expanded Assembly-CSharp from the local installs and
upserts them into the ReviewedBuilds entries in Source/RealEarth/BuildGuard.cs.
Run after verifying a NEW game version (live soak + hook binds green) so the
fail-closed build guard does not block the updated build.

Upsert, not replace: the allowlist means "hooks were verified against this
assembly", so rows for builds that are no longer installed (reviewed history)
stay.

Usage: python3 scripts/refresh_build_guard.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "Source" / "RealEarth" / "BuildGuard.cs"
GAME = Path.home() / ".local/share/Steam/steamapps/common/7 Days To Die"
DEDI = Path.home() / ".local/share/Steam/steamapps/common/7 Days to Die Dedicated Server"

# Game build these installs are expected to hold. Bump with the retarget so the
# labels written here match docs/GAME_VERSION.md.
VERSION_LABEL = "V3.3.0 (b18)"

ENTRY_RE = re.compile(r'\{"([0-9a-f]{64})", "([^"]*)"\},')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_entries() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    # Prefer the .re_stock_bak (true stock) over the live DLL (may be expanded).
    managed = "Managed/Assembly-CSharp.dll"
    client_data = GAME / "7DaysToDie_Data"
    dedi_data = DEDI / "7DaysToDieServer_Data"
    for label, path in (
        (f"{VERSION_LABEL} stock (client bak)", client_data / f"{managed}.re_stock_bak"),
        (f"{VERSION_LABEL} stock (dedi bak)", dedi_data / f"{managed}.re_stock_bak"),
        (f"{VERSION_LABEL} live client", client_data / managed),
        (f"{VERSION_LABEL} live dedi", dedi_data / managed),
    ):
        if path.is_file():
            entries.append((sha256(path), label))
    return entries


def main() -> int:
    local = local_entries()
    if not local:
        print("no Assembly-CSharp found; nothing to refresh", file=sys.stderr)
        return 1

    src = GUARD.read_text(encoding="utf-8")
    start = src.index("ReviewedBuilds =")
    end = src.index("};", start)
    old = ENTRY_RE.findall(src[start:end])
    local_hashes = {h for h, _ in local}
    kept = [(h, label) for h, label in old if h not in local_hashes]
    merged = local + kept

    body = "\n".join(f'                {{"{h}", "{label}"}},' for h, label in merged)
    new_block = (
        "ReviewedBuilds =\n"
        "            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)\n"
        "            {\n" + body + "\n            };"
    )
    src = src[:start] + new_block + src[end + 2 :]
    GUARD.write_text(src, encoding="utf-8")
    print(f"allowlist now {len(merged)} reviewed build(s) in {GUARD.name}:")
    for h, label in merged:
        print(f"  {h[:16]}... {label}")
    print(f"verified locally: {len(local)}; kept reviewed history: {len(kept)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
