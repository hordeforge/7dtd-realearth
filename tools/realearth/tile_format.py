"""RealEarth tile (.rte) binary format + manifest.

See DESIGN.md for the field meanings.
"""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from realearth import DEFAULT_SEA_LEVEL_GAME_Y

MAGIC = b"RTE1"
HEADER_STRUCT = struct.Struct("<4siiHHIII")  # magic, tx, tz, ver, flags, w, h, reserved
FORMAT_VERSION = 1

FLAG_HAS_POPULATION = 1 << 0
FLAG_HAS_LANDCOVER = 1 << 1
FLAG_HAS_POI = 1 << 2

# Hostile-header guard: real packs use 512x512 tiles; anything larger than this
# would allocate unbounded memory while decoding an untrusted pack.
MAX_TILE_SAMPLES = 4096 * 4096


@dataclass
class EarthTile:
    tile_x: int
    tile_z: int
    elevation_m: np.ndarray  # float32 or int16, shape (h, w), meters ASL
    landcover: np.ndarray | None = None  # uint8 (h, w)
    population: np.ndarray | None = None  # uint8 (h, w) log-scaled
    poi_blob: bytes = b""
    version: int = FORMAT_VERSION

    def __post_init__(self) -> None:
        if self.elevation_m.ndim != 2:
            raise ValueError("elevation_m must be 2D")
        self.elevation_m = np.asarray(self.elevation_m)
        h, w = self.elevation_m.shape
        if w <= 0 or h <= 0 or w * h > MAX_TILE_SAMPLES:
            # Every reader (decode_tile, the viewer mosaic, RteTile.Decode) caps
            # the sample count; refuse at the writer so an oversized tile_size
            # cannot produce a pack its own toolchain rejects.
            raise ValueError(f"tile dims out of range: {w}x{h}")
        if self.landcover is not None:
            self.landcover = np.asarray(self.landcover, dtype=np.uint8)
            if self.landcover.shape != (h, w):
                raise ValueError("landcover shape mismatch")
        if self.population is not None:
            self.population = np.asarray(self.population, dtype=np.uint8)
            if self.population.shape != (h, w):
                raise ValueError("population shape mismatch")

    @property
    def height(self) -> int:
        return int(self.elevation_m.shape[0])

    @property
    def width(self) -> int:
        return int(self.elevation_m.shape[1])

    def flags(self) -> int:
        f = 0
        if self.population is not None:
            f |= FLAG_HAS_POPULATION
        if self.landcover is not None:
            f |= FLAG_HAS_LANDCOVER
        if self.poi_blob:
            f |= FLAG_HAS_POI
        return f


def encode_tile(tile: EarthTile) -> bytes:
    """Serialize tile to .rte bytes."""
    elev = np.asarray(tile.elevation_m, dtype=np.float32)
    elev_u16 = elevation_m_to_u16(elev)
    elev_z = zlib.compress(elev_u16.tobytes(), level=6)

    parts: list[bytes] = []
    header = HEADER_STRUCT.pack(
        MAGIC,
        tile.tile_x,
        tile.tile_z,
        tile.version,
        tile.flags(),
        tile.width,
        tile.height,
        0,
    )
    parts.append(header)
    parts.append(struct.pack("<I", len(elev_z)))
    parts.append(elev_z)

    if tile.landcover is not None:
        lc_z = zlib.compress(np.asarray(tile.landcover, dtype=np.uint8).tobytes(), level=6)
        parts.append(struct.pack("<I", len(lc_z)))
        parts.append(lc_z)

    if tile.population is not None:
        pop_z = zlib.compress(np.asarray(tile.population, dtype=np.uint8).tobytes(), level=6)
        parts.append(struct.pack("<I", len(pop_z)))
        parts.append(pop_z)

    if tile.poi_blob:
        parts.append(struct.pack("<I", len(tile.poi_blob)))
        parts.append(tile.poi_blob)

    return b"".join(parts)


def _inflate_exact(blob: bytes, expected: int) -> bytes:
    """zlib-decompress with an output cap; reject size mismatches (decompress-bomb guard).

    Corrupt streams surface as ValueError like every other malformed-tile
    rejection: callers treat ValueError as the decoder's failure contract and
    must never see a raw zlib.error across this trust boundary.
    """
    d = zlib.decompressobj()
    try:
        # No flush(): it inflates without the cap and would defeat the bomb guard.
        out = d.decompress(blob, expected + 1)
    except zlib.error as e:
        raise ValueError(f"corrupt compressed section: {e}") from e
    if len(out) != expected or not d.eof or d.unused_data or d.unconsumed_tail:
        raise ValueError("decompressed payload size mismatch")
    return out


def _section(data: bytes, off: int, expected_raw: int) -> tuple[bytes, int]:
    """Read one length-prefixed compressed section; return (raw bytes, next offset)."""
    if off + 4 > len(data):
        raise ValueError("truncated section header")
    n = struct.unpack_from("<I", data, off)[0]
    off += 4
    if n < 0 or off + n > len(data):
        raise ValueError(f"section length out of range: {n}")
    if n > 16 * 1024 * 1024:
        raise ValueError(f"section too large: {n}")
    raw = _inflate_exact(data[off : off + n], expected_raw)
    return raw, off + n


def decode_tile(data: bytes) -> EarthTile:
    """Deserialize .rte bytes."""
    if len(data) < HEADER_STRUCT.size:
        raise ValueError("tile too short")
    magic, tx, tz, ver, flags, w, h, _ = HEADER_STRUCT.unpack_from(data, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic: {magic!r}")
    if ver > FORMAT_VERSION:
        # Fail closed on future formats: a v2 layout change must never be
        # silently misdecoded as v1 (garbage columns read as valid terrain).
        raise ValueError(f"unsupported tile version: {ver} (max {FORMAT_VERSION})")
    if w <= 0 or h <= 0 or w * h > MAX_TILE_SAMPLES:
        raise ValueError(f"tile dims out of range: {w}x{h}")
    samples = w * h
    off = HEADER_STRUCT.size

    elev_raw, off = _section(data, off, samples * 2)
    # Payload is little-endian per the format contract (matches the C# decoder,
    # which reads the low byte first); never rely on host byte order here.
    elev_u16 = np.frombuffer(elev_raw, dtype="<u2").reshape((h, w))
    elevation = u16_to_elevation_m(elev_u16)

    landcover = None
    population = None
    poi_blob = b""

    if flags & FLAG_HAS_LANDCOVER:
        raw, off = _section(data, off, samples)
        landcover = np.frombuffer(raw, dtype=np.uint8).reshape((h, w)).copy()

    if flags & FLAG_HAS_POPULATION:
        raw, off = _section(data, off, samples)
        population = np.frombuffer(raw, dtype=np.uint8).reshape((h, w)).copy()

    if flags & FLAG_HAS_POI and off < len(data):
        if off + 4 > len(data):
            raise ValueError("truncated POI header")
        n = struct.unpack_from("<I", data, off)[0]
        off += 4
        if n < 0 or off + n > len(data) or n > 4 * 1024 * 1024:
            raise ValueError(f"POI length out of range: {n}")
        poi_blob = data[off : off + n]

    return EarthTile(
        tile_x=tx,
        tile_z=tz,
        elevation_m=elevation,
        landcover=landcover,
        population=population,
        poi_blob=poi_blob,
        version=ver,
    )


def write_tile(path: Path, tile: EarthTile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_tile(tile))


def read_tile(path: Path) -> EarthTile:
    return decode_tile(path.read_bytes())


def tile_path(root: Path, tx: int, tz: int) -> Path:
    return root / "tiles" / f"{tz}" / f"{tx}.rte"


# Elevation packed as little-endian uint16: value = meters_asl + 11000
# (covers trenches to Everest+; byte order must match the C# runtime decoder).
ELEV_OFFSET_M = 11_000


def elevation_m_to_u16(elev: np.ndarray) -> np.ndarray:
    # Round to the nearest meter: Terrarium decode yields B/256 fractions, and a
    # plain astype(uint16) would truncate toward zero, biasing every stored
    # column downward by up to 1 m on a 1 m = 1 block product. Non-finite input
    # fails closed to 0 m ASL (matches the C# missing-sample placeholder) instead
    # of casting NaN to platform-garbage. np.nan_to_num maps +/-inf to the float
    # extremes, which rint+clip would pin to the uint16 rails (a 54535 m peak or
    # the -11000 m floor), so the finite mask is applied before the offset.
    v = np.asarray(elev, dtype=np.float64)
    v = np.where(np.isfinite(v), v, 0.0)
    return np.clip(np.rint(v + ELEV_OFFSET_M), 0, 65535).astype("<u2")


def u16_to_elevation_m(u: np.ndarray) -> np.ndarray:
    return u.astype(np.float32) - ELEV_OFFSET_M


def _manifest_int(d: dict[str, Any], key: str, default: int) -> int:
    """Read an integer manifest member; ValueError on anything else.

    The manifest ships inside a pack that can come from a shared pack or a CDN
    mirror, so a member is untrusted. `1e999` parses as inf and `int(inf)`
    raises OverflowError, which no caller catches, and `null` raises TypeError:
    both would abort a pipeline run with a traceback instead of a clean error.
    """
    raw = d.get(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        # OverflowError is the `1e999` path: json parses it to inf, int(inf) raises.
        raise ValueError(f"manifest {key} must be a finite integer, got {raw!r}") from exc


def _manifest_float(d: dict[str, Any], key: str, default: float) -> float:
    """Read a float manifest member; ValueError on non-numeric or non-finite."""
    raw = d.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"manifest {key} must be a number, got {raw!r}") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"manifest {key} must be finite, got {raw!r}")
    return value


def _manifest_list(d: dict[str, Any], key: str) -> list[Any]:
    """Read a list manifest member; ValueError when it is not iterable."""
    raw = d.get(key, [])
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
        raise ValueError(f"manifest {key} must be a list, got {raw!r}")
    return list(raw)


def _manifest_bbox(d: dict[str, Any]) -> dict[str, Any] | None:
    """Read the optional bbox object; ValueError when it is not an object.

    Consumers index the four members directly (lonlat_to_pack_block), so a
    string or list bbox has to be refused here rather than at the call site.
    """
    raw = d.get("bbox")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"manifest bbox must be an object, got {raw!r}")
    return raw


@dataclass
class Manifest:
    name: str = "RealEarth"
    version: int = 1
    tile_size: int = 512
    world_width: int = 40_075_017
    world_height: int = 20_003_931
    crs: str = "EPSG:4326"
    sea_level_game_y: int = DEFAULT_SEA_LEVEL_GAME_Y
    meters_per_block: float = 1.0
    bbox: dict[str, float] | None = None  # west,south,east,north if partial
    tiles: list[dict[str, int]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "tile_size": self.tile_size,
            "world_width": self.world_width,
            "world_height": self.world_height,
            "crs": self.crs,
            "sea_level_game_y": self.sea_level_game_y,
            "meters_per_block": self.meters_per_block,
            "bbox": self.bbox,
            "tiles": self.tiles,
            "sources": self.sources,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Manifest:
        # json.loads returns whatever the file held: null, a list or a bare
        # string decode fine and would raise AttributeError on the first get.
        if not isinstance(d, dict):
            raise ValueError(f"manifest must be a JSON object, got {type(d).__name__}")
        return cls(
            name=d.get("name", "RealEarth"),
            version=_manifest_int(d, "version", 1),
            tile_size=_manifest_int(d, "tile_size", 512),
            world_width=_manifest_int(d, "world_width", 40_075_017),
            world_height=_manifest_int(d, "world_height", 20_003_931),
            crs=d.get("crs", "EPSG:4326"),
            sea_level_game_y=_manifest_int(d, "sea_level_game_y", DEFAULT_SEA_LEVEL_GAME_Y),
            meters_per_block=_manifest_float(d, "meters_per_block", 1.0),
            bbox=_manifest_bbox(d),
            tiles=_manifest_list(d, "tiles"),
            sources=_manifest_list(d, "sources"),
            notes=d.get("notes", ""),
        )


def write_manifest(path: Path, manifest: Manifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False: manifest name/notes may carry non-ASCII world names.
    path.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path) -> Manifest:
    return Manifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
