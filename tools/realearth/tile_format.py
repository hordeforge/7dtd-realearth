"""RealEarth tile (.rte) binary format + manifest.

See DESIGN.md for the field meanings.
"""

from __future__ import annotations

import json
import struct
import zlib
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
    elev_u16 = _elevation_to_u16(elev)
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
        lc_z = zlib.compress(
            np.asarray(tile.landcover, dtype=np.uint8).tobytes(), level=6
        )
        parts.append(struct.pack("<I", len(lc_z)))
        parts.append(lc_z)

    if tile.population is not None:
        pop_z = zlib.compress(
            np.asarray(tile.population, dtype=np.uint8).tobytes(), level=6
        )
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
    elevation = _u16_to_elevation(elev_u16)

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
_ELEV_OFFSET_M = 11_000


def _elevation_to_u16(elev: np.ndarray) -> np.ndarray:
    # Round to the nearest meter: Terrarium decode yields B/256 fractions, and a
    # plain astype(uint16) would truncate toward zero, biasing every stored
    # column downward by up to 1 m on a 1 m = 1 block product. Non-finite input
    # fails closed to 0 m ASL (matches the C# missing-sample placeholder) instead
    # of casting NaN to platform-garbage.
    v = np.nan_to_num(np.asarray(elev, dtype=np.float64), nan=0.0)
    return np.clip(np.rint(v + _ELEV_OFFSET_M), 0, 65535).astype("<u2")


def _u16_to_elevation(u: np.ndarray) -> np.ndarray:
    return u.astype(np.float32) - _ELEV_OFFSET_M


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
        return cls(
            name=d.get("name", "RealEarth"),
            version=int(d.get("version", 1)),
            tile_size=int(d.get("tile_size", 512)),
            world_width=int(d.get("world_width", 40_075_017)),
            world_height=int(d.get("world_height", 20_003_931)),
            crs=d.get("crs", "EPSG:4326"),
            sea_level_game_y=int(d.get("sea_level_game_y", DEFAULT_SEA_LEVEL_GAME_Y)),
            meters_per_block=float(d.get("meters_per_block", 1.0)),
            bbox=d.get("bbox"),
            tiles=list(d.get("tiles", [])),
            sources=list(d.get("sources", [])),
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
