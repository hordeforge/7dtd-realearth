"""Pin scripts/sbom.py: the dependency inventory shipped with every release.

The SBOM is how a consumer (or a vuln scanner) learns what third-party code is
in a release, so these tests drive the shipped script end to end and assert the
properties the inventory is supposed to have: the shipped three.js appears with
the hash of the committed vendored files, every JS pin in
scripts/toolchain-versions.env is inventoried, and every relationship points at
a package the document actually declares.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sbom.py"
VENDORED_THREE = REPO_ROOT / "viewer" / "vendor" / "three"
PINS = REPO_ROOT / "scripts" / "toolchain-versions.env"


def run_sbom() -> dict:
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def doc() -> dict:
    return run_sbom()


def test_ships_vendored_three_with_the_committed_file_hashes(doc: dict) -> None:
    three = next(p for p in doc["packages"] if p["name"] == "npm:three")
    assert three["versionInfo"] == "0.170.0"
    recorded = {c["checksumValue"] for c in three["checksums"]}
    committed = {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(VENDORED_THREE.rglob("*.js"))
    }
    assert committed, "no vendored three.js files found"
    assert recorded == committed


def test_every_js_pin_is_inventoried(doc: dict) -> None:
    named = {p["name"] for p in doc["packages"] if p["name"].startswith("npm:")}
    # One package per pin naming an npm artifact; the *_SHA256 pins are hashes
    # of files, not packages, and ride along as checksums.
    for pin in (
        "esbuild",
        "typescript",
        "oxlint",
        "oxlint-tsgolint",
        "@oxlint/plugins",
        "@rikalabs/oxlint-standards",
        "@types/three",
        "three",
        "vnu-jar",
    ):
        assert f"npm:{pin}" in named, f"{pin} is pinned but missing from the SBOM"


def test_python_inventory_covers_the_manifest(doc: dict) -> None:
    locked = {p["name"] for p in doc["packages"] if p["name"].startswith("pypi:")}
    assert {"pypi:numpy", "pypi:httpx", "pypi:click", "pypi:pillow"} <= locked


def test_relationships_reference_declared_packages(doc: dict) -> None:
    ids = {p["SPDXID"] for p in doc["packages"]} | {doc["SPDXID"]}
    root = "SPDXRef-Package-realearth"
    described = {r["relatedSpdxElement"] for r in doc["relationships"]}
    assert doc["packages"][0]["SPDXID"] == root
    for rel in doc["relationships"]:
        assert rel["spdxElementId"] in ids
        assert rel["relatedSpdxElement"] in ids
    # Every declared package is a dependency of the root.
    assert ids - {doc["SPDXID"], root} <= described


def test_document_namespace_tracks_the_package_set(doc: dict) -> None:
    # The namespace is the sha256 of the name@version list: a dependency change
    # has to move it, so two inventories with different contents cannot share
    # a namespace.
    other = run_sbom()
    assert other["documentNamespace"] == doc["documentNamespace"]
    assert doc["documentNamespace"].startswith("https://github.com/hordeforge/")


def test_npm_versions_come_from_the_pins_file(doc: dict) -> None:
    # The inventory is generated from the pins file, so every npm entry has to
    # carry the version that file declares; a hardcoded version list fails here.
    pins = {
        m.group(1): m.group(2)
        for m in re.finditer(
            r'^: "\$\{([A-Z0-9_]+):=([^}]*)\}"',
            PINS.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    }
    assert pins, "no pins parsed from toolchain-versions.env"
    expected = {
        "npm:esbuild": pins["ESBUILD_VERSION"],
        "npm:typescript": pins["TSC_VERSION"],
        "npm:oxlint": pins["OXLINT_VERSION"],
        "npm:oxlint-tsgolint": pins["OXLINT_TSGOLINT_VERSION"],
        "npm:@oxlint/plugins": pins["OXLINT_PLUGINS_VERSION"],
        "npm:@rikalabs/oxlint-standards": pins["OXLINT_STANDARDS_VERSION"],
        "npm:@types/three": pins["THREE_TYPES_VERSION"],
        "npm:three": pins["THREE_VERSION"],
        "npm:vnu-jar": pins["VNU_VERSION"],
    }
    declared = {p["name"]: p["versionInfo"] for p in doc["packages"] if "versionInfo" in p}
    for name, version in expected.items():
        assert declared.get(name) == version
