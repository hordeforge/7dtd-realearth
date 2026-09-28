#!/usr/bin/env python3
"""Generate an SPDX 2.3 JSON dependency inventory for RealEarth releases.

Reads the lock/pin sources this repository builds against and writes one
deterministic SPDX document (same inputs, same bytes when SOURCE_DATE_EPOCH
is exported):

  tools/uv.lock                                        Python pipeline packages
  scripts/toolchain-versions.env                       JS build/lint toolchain pins
                                                        (and the sha256 of the
                                                        vendored three.js files)

No third-party libraries here: uv.lock is TOML (stdlib tomllib), the pins
file is KEY=VALUE shell.

Usage: sbom.py OUTPUT.spdx.json  (or - for stdout)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
NAMESPACE_BASE = "https://github.com/hordeforge/7dtd-realearth"
ROOT_SPDX_ID = "SPDXRef-Package-realearth"


def _created() -> str:
    """SPDX creation timestamp, pinned by SOURCE_DATE_EPOCH when set.

    Same convention as scripts/package_zip.sh: with the variable exported, two
    builds of the same source produce byte-identical SBOMs, so the document can
    be compared and rebuilt like any other release artifact. Without it the
    wall clock is the only thing left that differs.
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def toolchain_packages() -> list[dict[str, Any]]:
    """Pinned JS toolchain (npm packages the build/lint scripts install).

    every pin in scripts/toolchain-versions.env that names an npm package, so a
    new pin cannot be added without appearing in the release inventory.
    """
    env_text = (REPO / "scripts" / "toolchain-versions.env").read_text(encoding="utf-8")
    pins = {
        m.group(1): m.group(2)
        for m in re.finditer(r'^: "\$\{([A-Z0-9_]+):=([^}]*)\}"', env_text, re.MULTILINE)
    }
    npms = [
        ("esbuild", "ESBUILD_VERSION", False),
        ("typescript", "TSC_VERSION", False),
        ("oxlint", "OXLINT_VERSION", False),
        ("oxlint-tsgolint", "OXLINT_TSGOLINT_VERSION", False),
        ("@oxlint/plugins", "OXLINT_PLUGINS_VERSION", False),
        ("@rikalabs/oxlint-standards", "OXLINT_STANDARDS_VERSION", False),
        ("@types/three", "THREE_TYPES_VERSION", False),
        ("three", "THREE_VERSION", True),
        ("vnu-jar", "VNU_VERSION", False),
    ]
    out: list[dict[str, Any]] = []
    for name, pin, shipped in npms:
        version = pins.get(pin)
        if not version:
            continue
        purl_name = name.replace("@", "%40").replace("/", "%2f")
        if shipped:
            comment = (
                "shipped in release artifacts: vendored under viewer/vendor/three/ "
                "and served through viewer/index.html's importmap; file hashes "
                "pinned as THREE_*_SHA256 in scripts/toolchain-versions.env"
            )
            checksums = [
                {"algorithm": "SHA256", "checksumValue": pins[hash_pin]}
                for hash_pin in ("THREE_MODULE_SHA256", "THREE_ORBIT_CONTROLS_SHA256")
                if pins.get(hash_pin)
            ]
        else:
            comment = (
                "build/lint toolchain installed from scripts/js-toolchain.lock "
                "(or bunx); version-pinned in scripts/toolchain-versions.env; "
                "not shipped in release artifacts"
            )
            checksums = []
        out.append(
            {
                "SPDXID": None,
                "name": f"npm:{name}",
                "versionInfo": version,
                # SPDX 2.3: the npm registry is not the artifact. The exact
                # tarball URL is not recorded in-tree, so say so rather than
                # point at a page that is not the package.
                "downloadLocation": "NOASSERTION",
                "licenseConcluded": "NOASSERTION",
                "comment": comment,
                "checksums": checksums,
                "externalRefs": [_purl_ref(f"pkg:npm/{purl_name}@{version}")],
            }
        )
    out.extend(_anti_slop_package(pins))
    return out


def _anti_slop_package(pins: dict[str, str]) -> list[dict[str, Any]]:
    """The anti-slop oxlint plugin: git-pinned source, not an npm release."""
    commit = pins.get("ANTI_SLOP_SHA")
    if not commit:
        return []
    sha256 = pins.get("ANTI_SLOP_SHA256", "")
    return [
        {
            "SPDXID": None,
            "name": "github:dmmulroy/anti-slop",
            "versionInfo": commit,
            "downloadLocation": (f"https://github.com/dmmulroy/anti-slop/archive/{commit}.tar.gz"),
            "licenseConcluded": "NOASSERTION",
            "comment": (
                "oxlint plugin source vendored into the lint toolchain cache by "
                "scripts/install-js-toolchain.sh; not shipped in release artifacts"
            ),
            "checksums": ([{"algorithm": "SHA256", "checksumValue": sha256}] if sha256 else []),
            "externalRefs": [_purl_ref(f"pkg:github/dmmulroy/anti-slop@{commit}")],
        }
    ]


def build() -> dict[str, Any]:
    entries = toolchain_packages() + python_packages()
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
            "created": _created(),
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
            # One DEPENDS_ON per entry: a consumer or vuln scanner follows
            # relationships, so a single one would hide the whole inventory.
            *(
                {
                    "spdxElementId": ROOT_SPDX_ID,
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": pkg["SPDXID"],
                }
                for pkg in packages
                if pkg["SPDXID"] != ROOT_SPDX_ID
            ),
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
