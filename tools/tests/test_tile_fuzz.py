"""Deterministic mutation fuzz target for the .rte tile decoder.

decode_tile() is the trust boundary for pack files that can arrive from
untrusted sources (shared packs, CDN mirrors); Source/RealEarth/RteTile.cs
decodes the same layout inside the running game server. Unit tests pin known
bad cases; this harness explores the space around them with seeded,
reproducible mutations and asserts decoder invariants so logic bugs become
visible instead of relying on "did not crash":

- only ValueError may escape decode (any other exception is a defect)
- a successful decode must satisfy shape/version/sample-count invariants
- decode(encode(tile)) reproduces the tile exactly for every generated tile
  (pair assertion across the encode/decode boundary)
"""

import random
import struct
import zlib

import numpy as np

from realearth.settlements import encode_poi_blob
from realearth.tile_format import (
    FLAG_HAS_LANDCOVER,
    FLAG_HAS_POPULATION,
    FORMAT_VERSION,
    HEADER_STRUCT,
    MAGIC,
    MAX_TILE_SAMPLES,
    EarthTile,
    decode_tile,
    encode_tile,
)

_SEED = 20260826
_ITERATIONS = 400

_SHAPES = [(1, 1), (2, 3), (7, 5), (16, 16), (33, 21), (64, 64)]


def _random_tile(rng: random.Random) -> EarthTile:
    h, w = rng.choice(_SHAPES)
    elev = rng.randint(-11_000, 9_000) * np.ones((h, w), dtype=np.float32)
    noise = rng.choices(range(-50, 50), k=h * w)
    elev += np.array(noise, dtype=np.float32).reshape(h, w)
    lc = pop = None
    poi = b""
    if rng.random() < 0.7:
        lc = np.frombuffer(rng.randbytes(h * w), dtype=np.uint8).reshape(h, w)
    if rng.random() < 0.7:
        pop = np.frombuffer(rng.randbytes(h * w), dtype=np.uint8).reshape(h, w)
    if rng.random() < 0.5:
        plan = [
            {
                "name": f"p{i}",
                "band": rng.choice(["town", "city", "wilderness"]),
                "local_x": rng.randrange(w),
                "local_z": rng.randrange(h),
            }
            for i in range(rng.randrange(4))
        ]
        poi = encode_poi_blob(plan)
    return EarthTile(
        tile_x=rng.randint(-(2**31), 2**31 - 1),
        tile_z=rng.randint(-(2**31), 2**31 - 1),
        elevation_m=elev,
        landcover=lc,
        population=pop,
        poi_blob=poi,
    )


def _assert_decoded_invariants(tile: EarthTile) -> None:
    """Invariants every successful decode must hold, valid input or not."""
    h, w = tile.elevation_m.shape
    assert tile.elevation_m.ndim == 2
    assert w > 0 and h > 0 and w * h <= MAX_TILE_SAMPLES
    assert tile.version <= FORMAT_VERSION
    assert bool(np.isfinite(tile.elevation_m).all())
    if tile.landcover is not None:
        assert tile.landcover.shape == (h, w)
    if tile.population is not None:
        assert tile.population.shape == (h, w)


def _assert_roundtrip(tile: EarthTile) -> None:
    back = decode_tile(encode_tile(tile))
    assert back.tile_x == tile.tile_x
    assert back.tile_z == tile.tile_z
    assert back.version == tile.version
    assert back.flags() == tile.flags()
    assert back.elevation_m.shape == tile.elevation_m.shape
    # Elevation values are integer meters inside the u16 band: packing is exact.
    assert np.array_equal(back.elevation_m, tile.elevation_m)
    assert tile.landcover is None or (
        back.landcover is not None and (back.landcover == tile.landcover).all()
    )
    assert tile.population is None or (
        back.population is not None and (back.population == tile.population).all()
    )
    assert back.poi_blob == tile.poi_blob


def _decode_mutant(raw: bytes) -> str:
    """Decode one mutated byte string; return 'ok' or the rejection class."""
    try:
        t = decode_tile(raw)
    except ValueError:
        return "rejected"
    _assert_decoded_invariants(t)
    return "ok"


def test_fuzz_decode_rejects_or_satisfies_invariants():
    rng = random.Random(_SEED)

    # Round-trip pair assertions on valid tiles first: the decoder must agree
    # with the encoder before mutations are meaningful.
    for _ in range(20):
        _assert_roundtrip(_random_tile(rng))

    corpus = [encode_tile(_random_tile(rng)) for _ in range(8)]
    ok = rejected = 0
    for i in range(_ITERATIONS):
        base = bytearray(rng.choice(corpus))
        mode = i % 6
        if mode == 0:  # truncate at a pseudo-random prefix
            del base[rng.randrange(len(base)) :]
        elif mode == 1:  # bit flips anywhere
            for _ in range(rng.randint(1, 8)):
                base[rng.randrange(len(base))] ^= 1 << rng.randrange(8)
        elif mode == 2:  # corrupt only the fixed header fields
            pos = rng.choice((4, 8, 12, 14, 16, 20, 24))
            base[pos : pos + 4] = rng.randbytes(min(4, len(base) - pos))
        elif mode == 3:  # hostile dims/versions/flags via structured repack
            header = HEADER_STRUCT.pack(
                MAGIC,
                0,
                0,
                rng.choice((0, 1, 2, 3, 65_535)),
                rng.choice((0, 7, 15, 255)),
                rng.choice((0, 1, 4096, 4097, 1 << 31, 0xFF_FF_FF_FF)),
                rng.choice((1, 2, 512, 1 << 31, 0xFF_FF_FF_FF)),
                0,
            )
            base = bytearray(header + bytes(base[HEADER_STRUCT.size :]))
        elif mode == 4:  # section length lies: huge, negative-looking, truncated
            off = HEADER_STRUCT.size
            if len(base) >= off + 4:
                base[off : off + 4] = struct.pack(
                    "<I", rng.choice((0, 1 << 30, 16 * 1024 * 1024 + 1, 0xFFFF_FFFF))
                )
        else:  # compressed section replaced by junk or a bomb
            bomb = zlib.compress(b"\x00" * 4096, level=6)
            body = rng.choice((b"garbage!", bomb, b"", b"\x78\x9c\x00"))
            base = (
                base[: HEADER_STRUCT.size]
                + struct.pack("<I", len(body))
                + body
                + base[HEADER_STRUCT.size + 4 :]
            )
        outcome = _decode_mutant(bytes(base))
        ok += outcome == "ok"
        rejected += outcome == "rejected"

    # The mutation operators above must actually reach both outcomes; a run
    # where nothing decodes (or nothing is rejected) means the harness rotted.
    assert ok > 0 and rejected > 0


def test_fuzz_decode_random_bytes_never_escapes_valueerror():
    rng = random.Random(_SEED + 1)
    for _ in range(200):
        payload = rng.randbytes(rng.randrange(0, 256))
        if rng.random() < 0.5:  # half start with valid magic to get past gate 1
            payload = MAGIC + payload[len(MAGIC) :] if len(payload) >= 4 else payload
        try:
            t = decode_tile(payload)
        except ValueError:
            continue
        _assert_decoded_invariants(t)


def test_fuzz_poi_flags_without_sections_stay_bounded():
    # Flags claiming sections that are absent are the classic parser trap:
    # every combination must either reject or decode within invariants.
    for flags in range(16):
        body = struct.pack("<I", 0)
        raw = HEADER_STRUCT.pack(MAGIC, 0, 0, 1, flags, 1, 1, 0)
        if flags & FLAG_HAS_LANDCOVER or flags & FLAG_HAS_POPULATION:
            raw += body
        outcome = _decode_mutant(raw)
        assert outcome in ("ok", "rejected")
