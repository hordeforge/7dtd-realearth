"""Place-name Unicode handling across the pipeline boundary.

The convention is NFC at ingestion (tools/realearth/settlements.py
normalize_place_name; region.py _place_name_key adds casefold for identity).
The C# runtime consumes pack settlements.json and merges it with its own seed
places, so it must apply the same normalization or an NFD spelling of a name
(macOS-written JSON, some map exports) survives Ordinal dedup as a second
place: duplicate map labels plus double POI stamps at the same block.
"""

from __future__ import annotations

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


def test_pack_file_reads_declare_utf8_encoding():
    """External JSON/text reads in the mod declare UTF-8 instead of relying on
    the platform default decoder."""
    city = _read("CityMapLabels.cs")
    assert "File.ReadAllText(path, Encoding.UTF8)" in city
    session = _read("SessionStateStore.cs")
    assert "File.ReadAllText(p, Encoding.UTF8)" in session
    modapi = _read("ModApi.cs")
    assert "File.ReadAllText(manPath, Encoding.UTF8)" in modapi


def test_seed_place_literals_are_nfc():
    """A non-NFC literal here would fight the normalization contract silently."""
    src = _read("CityMapLabels.cs")
    assert src == unicodedata.normalize(
        "NFC", src
    ), "CityMapLabels.cs contains non-NFC text in seed names or comments"
