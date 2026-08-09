"""Resolve Steam/Proton 7DTD userdata paths for GeneratedWorlds install.

Windows Proton client (this machine) uses:
  steamapps/compatdata/251570/pfx/drive_c/users/steamuser/AppData/Roaming/7DaysToDie

Native Linux client/server may use:
  ~/.local/share/7DaysToDie

Install must put GeneratedWorlds under the path the running client actually uses.
"""

from __future__ import annotations

import os
from pathlib import Path

STEAM_APPID = "251570"


def steam_roots() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        Path(os.environ["STEAM_DIR"]) if os.environ.get("STEAM_DIR") else None,
    ]
    out: list[Path] = []
    for c in candidates:
        if c is None:
            continue
        if c.is_dir() and c not in out:
            out.append(c)
    return out


def proton_userdata(appid: str = STEAM_APPID) -> Path | None:
    """Return Proton Windows Roaming 7DaysToDie folder if present."""
    for root in steam_roots():
        p = (
            root
            / "steamapps"
            / "compatdata"
            / appid
            / "pfx"
            / "drive_c"
            / "users"
            / "steamuser"
            / "AppData"
            / "Roaming"
            / "7DaysToDie"
        )
        if p.is_dir():
            return p
    return None


def native_linux_userdata() -> Path:
    return Path.home() / ".local/share/7DaysToDie"


def client_generated_worlds_targets(
    *,
    prefer_proton: bool = True,
    also_native: bool = True,
    appid: str = STEAM_APPID,
) -> list[Path]:
    """Directories that should receive GeneratedWorlds/RealEarth for this machine.

    For Steam/Proton Windows client, Proton Roaming is required.
    Native Linux path is optional (dedicated server / native client).
    """
    targets: list[Path] = []
    proton = proton_userdata(appid)
    native = native_linux_userdata()
    if prefer_proton and proton is not None:
        targets.append(proton / "GeneratedWorlds")
    if also_native:
        # Always include native if different (server smoke tests / native client)
        n = native / "GeneratedWorlds"
        if n not in targets:
            targets.append(n)
    if not targets:
        targets.append(native / "GeneratedWorlds")
    return targets


def primary_client_userdata() -> Path:
    """Best userdata root for the Proton Windows client on this machine."""
    p = proton_userdata()
    if p is not None:
        return p
    return native_linux_userdata()
