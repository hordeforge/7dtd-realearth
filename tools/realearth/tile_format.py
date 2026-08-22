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


def decode_tile(data: bytes) -> EarthTile:
    """Deserialize .rte bytes."""
    if len(data) < HEADER_STRUCT.size:
        raise ValueError("tile too short")
    magic, tx, tz, ver, flags, w, h, _ = HEADER_STRUCT.unpack_from(data, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic: {magic!r}")
    off = HEADER_STRUCT.size

    elev_len = struct.unpack_from("<I", data, off)[0]
    off += 4
    elev_raw = zlib.decompress(data[off : off + elev_len])
    off += elev_len
    elev_u16 = np.frombuffer(elev_raw, dtype=np.uint16).reshape((h, w))
    elevation = _u16_to_elevation(elev_u16)

    landcover = None
    population = None
    poi_blob = b""

    if flags & FLAG_HAS_LANDCOVER:
        n = struct.unpack_from("<I", data, off)[0]
        off += 4
        raw = zlib.decompress(data[off : off + n])
        off += n
        landcover = np.frombuffer(raw, dtype=np.uint8).reshape((h, w)).copy()

    if flags & FLAG_HAS_POPULATION:
        n = struct.unpack_from("<I", data, off)[0]
        off += 4
        raw = zlib.decompress(data[off : off + n])
        off += n
        population = np.frombuffer(raw, dtype=np.uint8).reshape((h, w)).copy()

    if flags & FLAG_HAS_POI and off < len(data):
        n = struct.unpack_from("<I", data, off)[0]
        off += 4
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


# Elevation packed as uint16: value = meters_asl + 11000 (covers trenches to Everest+)
_ELEV_OFFSET_M = 11_000
_ELEV_SCALE = 1  # meters


def _elevation_to_u16(elev: np.ndarray) -> np.ndarray:
    v = np.clip(elev + _ELEV_OFFSET_M, 0, 65535)
    return v.astype(np.uint16)


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
            sea_level_game_y=int(
                d.get("sea_level_game_y", DEFAULT_SEA_LEVEL_GAME_Y)
            ),
            meters_per_block=float(d.get("meters_per_block", 1.0)),
            bbox=d.get("bbox"),
            tiles=list(d.get("tiles", [])),
            sources=list(d.get("sources", [])),
            notes=d.get("notes", ""),
        )


def write_manifest(path: Path, manifest: Manifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")


def read_manifest(path: Path) -> Manifest:
    return Manifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
