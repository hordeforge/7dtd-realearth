"""Place-name Unicode handling across the pipeline boundary.

The convention is NFC at ingestion (tools/realearth/settlements.py
normalize_place_name; region.py _place_name_key adds casefold for identity).
The C# runtime consumes pack settlements.json and merges it with its own seed
places, so it must apply the same normalization or an NFD spelling of a name
(macOS-written JSON, some map exports) survives Ordinal dedup as a second
place: duplicate map labels plus double POI stamps at the same block.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from realearth.settlements import normalize_place_name

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Source" / "RealEarth"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def test_normalize_place_name_folds_nfd_and_keeps_nfc_idempotent():
    nfd = unicodedata.normalize("NFD", "São Paulo")
    assert normalize_place_name(nfd) == "São Paulo"
    assert normalize_place_name("São Paulo") == "São Paulo"


def test_city_map_labels_normalizes_names_at_ingestion():
    src = _read("CityMapLabels.cs")
    assert (
        "NormalizationForm.FormC" in src
    ), "CityMapLabels must define the NFC canonical form helper"
    # Helper body really normalizes (not a passthrough).
    helper = re.search(
        r"internal static string NormalizePlaceName\(string name\)\s*=>[^;]*"
        r"Normalize\(NormalizationForm\.FormC\)",
        src,
    )
    assert helper, "NormalizePlaceName must call string.Normalize(FormC)"
    # Applied at both ingestion points: parsed JSON rows and built-in seeds.
    parse = re.search(r"place\.Name = NormalizePlaceName\(name\);", src)
    assert parse, "parsed settlement rows must be NFC-normalized"
    seed = re.search(r"Name = NormalizePlaceName\(s\.n\),", src)
    assert seed, "seed places must be NFC-normalized"


def test_city_map_labels_strips_control_chars_at_ingestion():
    """UnescapeJson decodes \\n / \\r / \\uXXXX into raw control chars; names are
    then echoed into the server log (discovery + POI stamp lines), so ingestion
    must strip Unicode control chars or a hostile pack can forge log lines."""
    src = _read("CityMapLabels.cs")
    helper = re.search(
        r"internal static string StripControlChars\(string s\)[^}]*char\.IsControl",
        src,
        re.DOTALL,
    )
    assert helper, "CityMapLabels must define a char.IsControl-based stripper"
    # The stripper is applied inside the same canonicalization the parsed rows
    # go through (NormalizePlaceName wraps it), so every ingestion point is
    # covered without a second application site to forget.
    normalize = re.search(
        r"internal static string NormalizePlaceName\(string name\)\s*=>[^;]*"
        r"StripControlChars\([^;]*Normalize\(NormalizationForm\.FormC\)",
        src,
    )
    assert normalize, (
        "NormalizePlaceName must strip control chars after FormC normalization "
        "(post-unescape order matters)"
    )


def test_pack_file_reads_declare_utf8_encoding():
    """External JSON/text reads in the mod declare UTF-8 instead of relying on
    the platform default decoder."""
    city = _read("CityMapLabels.cs")
    assert "File.ReadAllText(path, Encoding.UTF8)" in city
    session = _read("SessionStateStore.cs")
    assert "File.ReadAllText(p, Encoding.UTF8)" in session
    manifest = _read("PackManifest.cs")
    assert "File.ReadAllText(manPath, Encoding.UTF8)" in manifest


def test_seed_place_literals_are_nfc():
    """A non-NFC literal here would fight the normalization contract silently."""
    src = _read("CityMapLabels.cs")
    assert src == unicodedata.normalize(
        "NFC", src
    ), "CityMapLabels.cs contains non-NFC text in seed names or comments"


def test_generated_world_normalizes_pack_settlement_names(tmp_path: Path):
    """The bake path reads settlements.json straight off disk, so it is an
    ingestion point like the GeoJSON loader: a pack written on macOS carries NFD
    names and every other stage treats the composed form as canonical."""
    from realearth.generated_world import bake_generated_world
    from realearth.region import build_region

    nfd = unicodedata.normalize("NFD", "São Paulo")
    pack = tmp_path / "pack"
    build_region(
        -47.0,
        -24.2,
        -46.0,
        -23.0,
        pack,
        resolution_m=200.0,
        source="synthetic",
        name="NfdPack",
        max_dim=128,
        also_export_7dtd=False,
    )
    settlements_path = pack / "settlements.json"
    rows = json.loads(settlements_path.read_text(encoding="utf-8"))
    rows.append({"name": nfd, "lon": -46.63, "lat": -23.55, "population": 12_000_000})
    settlements_path.write_text(json.dumps(rows, ensure_ascii=False) + "\n", encoding="utf-8")

    ttw = tmp_path / "main.ttw"
    ttw.write_bytes(b"ttw\x00" + b"\x00" * 100)
    out = tmp_path / "world"
    bake_generated_world(pack, out, size=2048, name="NfdWorld", ttw_template=ttw)

    cities = json.loads((out / "cities.json").read_text(encoding="utf-8"))
    names = [c["name"] for c in cities["cores"]]
    assert "São Paulo" in names
    assert nfd not in names


def test_region_core_name_match_uses_the_identity_key():
    """The settlements.json row inherits a snapped core's measured edge only
    when the names match; a raw == misses an NFD or differently-cased spelling
    of the same place, the exact case _place_name_key exists for."""
    src = (ROOT / "tools" / "realearth" / "region.py").read_text(encoding="utf-8")
    assert "if c.name == s.name" not in src, (
        "region.py must match a settlement to its core with _place_name_key, "
        "not raw string equality"
    )
    assert re.search(r"if _place_name_key\(c\.name\) == s_key and c\.edge_radius_m > 0", src)
