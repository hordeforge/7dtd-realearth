#!/usr/bin/env python3
"""Generate an SPDX 2.3 JSON dependency inventory for RealEarth releases.

Reads the lock/pin sources this repository builds against and writes one
deterministic SPDX document (same inputs, same bytes modulo the timestamp):

  tools/uv.lock                                        Python pipeline packages
  tools/network_protocol_inspector/packages.lock.json  NuGet Mono.Cecil
  scripts/toolchain-versions.env                       JS build/lint toolchain pins

No third-party libraries here: uv.lock is TOML (stdlib tomllib),
packages.lock.json is JSON (stdlib json), the pins file is KEY=VALUE shell.

Usage: sbom.py OUTPUT.spdx.json  (or - for stdout)
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
NAMESPACE_BASE = "https://github.com/hordeforge/7dtd-realearth"
ROOT_SPDX_ID = "SPDXRef-Package-realearth"


def _purl_ref(locator: str) -> list[dict[str, str]]:
    return [
        {
            "referenceCategory": "PACKAGE-MANAGER",
            "referenceType": "purl",
            "referenceLocator": locator,
        }
    ]


def python_packages() -> list[dict[str, Any]]:
    """Every locked Python artifact: one entry per distinct name@version."""
    lock = tomllib.loads((REPO / "tools" / "uv.lock").read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for pkg in lock["package"]:
        # The root project (editable source) has no pinned artifact: skip it.
        version = str(pkg.get("version", ""))
        if not version:
            continue
        sha = ""
        if "sdist" in pkg:
            sha = str(pkg["sdist"].get("hash", ""))
        elif pkg.get("wheels"):
            sha = str(pkg["wheels"][0].get("hash", ""))
        registry = str(pkg.get("source", {}).get("registry", "https://pypi.org/simple"))
        name = str(pkg["name"])
        out.append(
            {
                "SPDXID": None,  # assigned by build()
                "name": f"pypi:{name}",
                "versionInfo": version,
                "downloadLocation": registry,
                "licenseConcluded": "NOASSERTION",
                "checksums": (
                    [{"algorithm": "SHA256", "checksumValue": sha.split(":", 1)[-1]}] if sha else []
                ),
                "externalRefs": [_purl_ref(f"pkg:pypi/{name}@{version}")],
            }
        )
    return out


def nuget_packages() -> list[dict[str, Any]]:
    """NuGet locks with content hashes (RestorePackagesWithLockFile)."""
    path = REPO / "tools" / "network_protocol_inspector" / "packages.lock.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for tfm, deps in data.get("dependencies", {}).items():
        for name, info in sorted(deps.items()):
            content_hash_b64 = str(info.get("contentHash", ""))
            digest = hashlib.sha256(content_hash_b64.encode("utf-8")).hexdigest()
            resolved = str(info.get("resolved", ""))
            out.append(
                {
                    "SPDXID": None,
                    "name": f"nuget:{name}",
                    "versionInfo": resolved,
                    "downloadLocation": f"https://www.nuget.org/packages/{name}/",
                    "licenseConcluded": "NOASSERTION",
                    "comment": (
                        f"target framework {tfm}; checksum is SHA256 over the "
                        "packages.lock.json contentHash string"
                    ),
                    "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
                    "externalRefs": [_purl_ref(f"pkg:nuget/{name}@{resolved}")],
                }
            )
    return out


def toolchain_packages() -> list[dict[str, Any]]:
    """Pinned JS build/lint toolchain (bunx-fetched npm packages)."""
    env_text = (REPO / "scripts" / "toolchain-versions.env").read_text(encoding="utf-8")
    pins = {
        m.group(1): m.group(2)
        for m in re.finditer(r'^: "\$\{([A-Z_]+):=([^}]*)\}"', env_text, re.MULTILINE)
    }
    npms = [
        ("esbuild", pins.get("ESBUILD_VERSION")),
        ("typescript", pins.get("TSC_VERSION")),
        ("oxlint", pins.get("OXLINT_VERSION")),
        ("@types/three", pins.get("THREE_TYPES_VERSION")),
        ("vnu-jar", pins.get("VNU_VERSION")),
    ]
    out: list[dict[str, Any]] = []
    for name, version in npms:
        if not version:
            continue
        purl_name = name.replace("@", "%40").replace("/", "%2f")
        out.append(
            {
                "SPDXID": None,
                "name": f"npm:{name}",
                "versionInfo": version,
                "downloadLocation": "https://registry.npmjs.org/",
                "licenseConcluded": "NOASSERTION",
                "comment": (
                    "build/lint toolchain fetched via bunx; version-pinned in "
                    "scripts/toolchain-versions.env; not shipped in release artifacts"
                ),
                "checksums": [],
                "externalRefs": [_purl_ref(f"pkg:npm/{purl_name}@{version}")],
            }
        )
    return out


def build() -> dict[str, Any]:
    entries = nuget_packages() + toolchain_packages() + python_packages()
    entries.sort(key=lambda p: (str(p["name"]), str(p["versionInfo"])))
    identity = ";".join(f"{p['name']}@{p['versionInfo']}" for p in entries)
    namespace = f"{NAMESPACE_BASE}/sbom/{hashlib.sha256(identity.encode()).hexdigest()}"

    packages: list[dict[str, Any]] = [
        {
            "SPDXID": ROOT_SPDX_ID,
            "name": "RealEarth",
            "downloadLocation": f"{NAMESPACE_BASE}.git",
            "filesAnalyzed": False,
            "licenseConcluded": "MIT",
            "copyrightText": "NOASSERTION",
            "comment": "root package: the RealEarth repository release this inventory describes",
        }
    ]
    for i, p in enumerate(entries):
        spdx_id = f"SPDXRef-{i + 1:03d}"
        p["SPDXID"] = spdx_id
        pkg: dict[str, Any] = {
            "SPDXID": spdx_id,
            "name": p["name"],
            "versionInfo": p["versionInfo"],
            "downloadLocation": p["downloadLocation"],
            "filesAnalyzed": False,
            "licenseConcluded": p["licenseConcluded"],
            "copyrightText": "NOASSERTION",
        }
        if p["checksums"]:
            pkg["checksums"] = p["checksums"]
        pkg["externalRefs"] = p["externalRefs"]
        if "comment" in p:
            pkg["comment"] = p["comment"]
        packages.append(pkg)

    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "realearth-dependencies",
        "documentNamespace": namespace,
        "creationInfo": {
            "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "creators": ["Tool:realearth-scripts-sbom"],
            "licenseListVersion": "3.25",
        },
        "packages": packages,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": ROOT_SPDX_ID,
            },
            {
                "spdxElementId": ROOT_SPDX_ID,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": f"SPDXRef-{i + 1:03d}",
            },
        ],
    }


def main() -> int:
    out_arg = sys.argv[1] if len(sys.argv) > 1 else "-"
    doc = json.dumps(build(), indent=1)
    if out_arg == "-":
        print(doc)
    else:
        Path(out_arg).write_text(doc + "\n", encoding="utf-8")
        print(f"sbom: wrote {out_arg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
