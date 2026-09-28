"""Deterministic mutation fuzz target for the Terrarium PNG decode path.

`_decode_tile_png` reads bytes that came off the network (AWS Open Data terrain
tiles) or out of the on-disk tile cache, and every `realearth fetch-elevation`
run hands whatever comes back to `decode_terrarium_png`, whose output becomes
the pack elevation. The contract callers rely on: a tile that cannot be decoded
is None (a hole the caller re-fetches), never an exception, and a decoded tile
carries meters inside the encoding range. These harnesses feed truncated,
mutated and structurally hostile PNGs in and assert that contract plus the
encoder/decoder pair on known RGB triples.
"""

from __future__ import annotations

import io
import random

import numpy as np
import pytest

from realearth.elevation import _decode_tile_png, decode_terrarium_png

Image = pytest.importorskip("PIL.Image", reason="Pillow decodes the fetched tiles")

_SEED = 20260928
_ITERATIONS = 200

# Terrarium: (R * 256 + G + B / 256) - 32768, so the encoding bounds every
# decoded sample whatever bytes the source delivered.
_MIN_M = -32768.0
_MAX_M = 255 * 256.0 + 255.0 + 255.0 / 256.0 - 32768.0

_SIZES = [(1, 1), (2, 3), (16, 16), (32, 32), (64, 64)]


def _png_bytes(rng: random.Random) -> bytes:
    h, w = rng.choice(_SIZES)
    rgb = np.frombuffer(rng.randbytes(h * w * 3), dtype=np.uint8).reshape(h, w, 3)
    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def _assert_decoded_invariants(elev: np.ndarray, h: int, w: int) -> None:
    assert elev.shape == (h, w)
    assert elev.dtype == np.float32
    assert bool(np.isfinite(elev).all())
    assert float(elev.min()) >= _MIN_M
    assert float(elev.max()) <= _MAX_M


def _decode_or_none(data: bytes) -> np.ndarray | None:
    """Run the tile decoder; assert its failure mode is a None, not a raise."""
    try:
        return _decode_tile_png(data)
    except (MemoryError, RecursionError) as exc:  # pragma: no cover - a real defect
        raise AssertionError(f"decoder died on {len(data)} bytes: {exc!r}") from exc


def test_fuzz_tile_png_mutations_never_raise():
    rng = random.Random(_SEED)
    corpus = [_png_bytes(rng) for _ in range(4)]
    decoded = 0
    for i in range(_ITERATIONS):
        base = bytearray(rng.choice(corpus))
        mode = i % 5
        if mode == 0:  # truncate mid-stream
            del base[rng.randrange(1, len(base)) :]
        elif mode == 1:  # bit flips, including inside chunk headers and CRCs
            for _ in range(rng.randint(1, 10)):
                base[rng.randrange(len(base))] ^= 1 << rng.randrange(8)
        elif mode == 2:  # declared chunk length lies
            pos = base.find(b"IDAT")
            if pos > 0:
                base[pos - 4 : pos] = rng.randbytes(4)
        elif mode == 3:  # IHDR dimensions and bit depth rewritten
            if base[:8] == b"\x89PNG\r\n\x1a\n" and len(base) > 33:
                base[16:29] = rng.choice((b"\x00" * 13, b"\xff" * 13, bytes(rng.randbytes(13))))
        else:  # whole payload replaced by junk or a hostile prefix
            base = bytearray(rng.randbytes(rng.randrange(0, 512)))
            if rng.random() < 0.5 and len(corpus[0]) > 8:
                base[:8] = corpus[0][:8]
        elev = _decode_or_none(bytes(base))
        if elev is None:
            continue
        decoded += 1
        assert elev.ndim == 2 and elev.shape[0] > 0 and elev.shape[1] > 0
        _assert_decoded_invariants(elev, elev.shape[0], elev.shape[1])

    # Both outcomes must occur: a run where nothing ever decodes means the
    # harness rotted, and one where nothing is ever rejected hides a crash.
    assert decoded > 0


def test_fuzz_decode_terrarium_array_shapes_and_dtypes():
    rng = random.Random(_SEED + 1)
    seen_ok = seen_rejected = 0
    for _ in range(_ITERATIONS):
        h = rng.randrange(0, 8)
        w = rng.randrange(0, 8)
        channels = rng.choice((1, 2, 3, 4, 5, 0))
        shape = (h, w, channels) if channels else (h, w)
        dtype = rng.choice((np.uint8, np.int16, np.float32, np.float64))
        rgb = np.frombuffer(rng.randbytes(max(0, h * w * channels)), dtype=np.uint8)
        arr = rgb.astype(dtype).reshape(shape) if h * w * channels else np.zeros(shape, dtype)
        try:
            out = decode_terrarium_png(arr)
        except ValueError:
            seen_rejected += 1
            continue
        seen_ok += 1
        assert out.shape == (h, w)
        assert bool(np.isfinite(out).all())
    assert seen_ok > 0 and seen_rejected > 0


def test_fuzz_terrarium_roundtrip_on_known_triples():
    """Pair assertion: encoded RGB decodes back to the meters it stands for."""
    rng = random.Random(_SEED + 2)
    for _ in range(200):
        r, g, b = (rng.randrange(256) for _ in range(3))
        arr = np.array([[[r, g, b, 255]]], dtype=np.uint8)  # RGBA input is accepted
        want = r * 256.0 + g + b / 256.0 - 32768.0
        got = decode_terrarium_png(arr)
        assert got.shape == (1, 1)
        assert float(got[0, 0]) == pytest.approx(want, abs=1e-4)

    # Extremes: the encoding floor and ceiling, plus sea level.
    for triple, want in (
        ((0, 0, 0), -32768.0),
        ((255, 255, 255), 32767.99609375),
        ((128, 0, 0), 0.0),  # 32768 - 32768 = 0 m ASL
    ):
        arr = np.array([[list(triple)]], dtype=np.uint8)
        assert float(decode_terrarium_png(arr)[0, 0]) == pytest.approx(want, abs=1e-4)
