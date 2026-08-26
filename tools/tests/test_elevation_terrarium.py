"""Unit tests for Terrarium decode, tile math, HTTP retry, tile cache (no network)."""

import os

import httpx
import numpy as np
import pytest

from realearth.elevation import (
    _get_with_retry,
    _lonlat_to_tile,
    _store_tile,
    decode_terrarium_png,
    fetch_region_terrarium,
)


def test_decode_terrarium_sea_levelish():
    # elev = R*256 + G + B/256 - 32768
    # want ~0 m: 32768 = R*256 + G → R=128, G=0, B=0 → 128*256 - 32768 = 0
    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    rgb[:, :, 0] = 128
    elev = decode_terrarium_png(rgb)
    assert elev.shape == (2, 2)
    assert abs(float(elev[0, 0])) < 0.01


def test_decode_terrarium_positive_height():
    # 100 m: 32768+100 = 32868 → R=128, G=100
    rgb = np.zeros((1, 1, 3), dtype=np.uint8)
    rgb[0, 0] = (128, 100, 0)
    elev = decode_terrarium_png(rgb)
    assert abs(float(elev[0, 0]) - 100.0) < 0.5


def test_lonlat_to_tile_known_points():
    # Equator / prime meridian at z=1 → tile roughly center of 2x2
    x, y = _lonlat_to_tile(0.0, 0.0, 1)
    assert 0 <= x <= 1
    assert 0 <= y <= 1
    # San Francisco-ish should be western US tile at z=5
    x, y = _lonlat_to_tile(-122.4, 37.8, 5)
    assert 0 <= x < 32
    assert 0 <= y < 32


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status = httpx.Response(
            status_code, request=httpx.Request("GET", "http://unit.test/tile")
        )

    @property
    def status_code(self) -> int:
        return self.status.status_code

    @property
    def request(self) -> httpx.Request:
        return self.status.request

    def raise_for_status(self) -> None:
        self.status.raise_for_status()


class _FlakyClient:
    """Fails N times with transport errors, then returns a response with `status`."""

    def __init__(self, failures: int, status: int = 200):
        self.failures = failures
        self.status = status
        self.calls = 0

    def get(self, url: str, params: dict | None = None):
        self.calls += 1
        if self.calls <= self.failures:
            raise httpx.ConnectError("connection reset")
        return _FakeResponse(self.status)


def test_get_with_retry_recovers_from_transient_transport_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    client = _FlakyClient(failures=2)
    r = _get_with_retry(client, "http://unit.test/tile")
    assert r.status_code == 200
    assert client.calls == 3


def test_get_with_retry_retries_5xx_then_raises(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    client = _FlakyClient(failures=0, status=503)
    with pytest.raises(httpx.HTTPStatusError):
        _get_with_retry(client, "http://unit.test/tile")
    assert client.calls == 3


def test_get_with_retry_exhausts_transport_errors_then_raises(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    client = _FlakyClient(failures=99)
    with pytest.raises(httpx.ConnectError):
        _get_with_retry(client, "http://unit.test/tile")
    assert client.calls == 3


def test_get_with_retry_does_not_retry_client_errors():
    client = _FlakyClient(failures=0, status=404)
    with pytest.raises(httpx.HTTPStatusError):
        _get_with_retry(client, "http://unit.test/tile")
    assert client.calls == 1


def test_get_with_retry_backoff_is_deterministic(monkeypatch):
    """Retry backoff must be a fixed schedule (no RNG) so runs stay reproducible."""
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    client = _FlakyClient(failures=99)
    with pytest.raises(httpx.ConnectError):
        _get_with_retry(client, "http://unit.test/tile")
    assert client.calls == 3
    assert sleeps == [0.5, 1.0]


class _FakeTileResponse:
    def __init__(self, content: bytes):
        self.status_code = 200
        self.content = content
        self.request = httpx.Request("GET", "http://unit.test/tile")

    def raise_for_status(self) -> None:
        pass


class _FakeTileClient:
    """Context-manager client serving one canned tile PNG; counts HTTP calls."""

    def __init__(self, png: bytes):
        self.png = png
        self.calls = 0

    def get(self, url: str, params: dict | None = None) -> _FakeTileResponse:
        self.calls += 1
        return _FakeTileResponse(self.png)

    def __enter__(self) -> "_FakeTileClient":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _tile_png() -> bytes:
    import io

    from PIL import Image

    rgb = np.zeros((256, 256, 3), dtype=np.uint8)
    rgb[:, :, 0] = 128  # 128*256 - 32768 = 0 m
    rgb[:, :, 1] = 100  # +100 m
    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


_BBOX = (-0.001, -0.001, 0.001, 0.001)


def test_terrarium_cache_serves_second_run_without_http(monkeypatch, tmp_path):
    """A cached region must rebuild offline: zero HTTP on the second run."""
    png = _tile_png()
    client = _FakeTileClient(png)
    monkeypatch.setattr(httpx, "Client", lambda **kw: client)

    a = fetch_region_terrarium(*_BBOX, 8, 8, zoom=1, cache_dir=tmp_path)
    first_run_calls = client.calls
    assert first_run_calls >= 1
    b = fetch_region_terrarium(*_BBOX, 8, 8, zoom=1, cache_dir=tmp_path)
    assert client.calls == first_run_calls  # second run made no new requests
    assert np.array_equal(a, b)


def test_terrarium_cache_env_default(monkeypatch, tmp_path):
    """RE_TERRARIUM_CACHE enables the cache without an explicit argument."""
    import realearth.elevation as el

    png = _tile_png()
    client = _FakeTileClient(png)
    monkeypatch.setattr(httpx, "Client", lambda **kw: client)
    monkeypatch.setenv("RE_TERRARIUM_CACHE", str(tmp_path / "tiles"))

    fetch_region_terrarium(*_BBOX, 8, 8, zoom=1)
    stored = list((tmp_path / "tiles").rglob("*.png"))
    assert stored, "fetched tiles must be persisted to the env-configured cache"
    assert el.terrarium_cache_dir() == tmp_path / "tiles"


def test_terrarium_cache_corrupt_entry_is_refetched(monkeypatch, tmp_path):
    """A corrupt cached PNG must never poison a rebuild: refetch overwrites it."""
    png = _tile_png()
    client = _FakeTileClient(png)
    monkeypatch.setattr(httpx, "Client", lambda **kw: client)

    # Poison every tile slot this bbox touches.
    west, south, east, north = _BBOX
    x0, y0 = _lonlat_to_tile(west, north, 1)
    x1, y1 = _lonlat_to_tile(east, south, 1)
    poisoned = 0
    for tx in range(min(x0, x1), max(x0, x1) + 1):
        for ty in range(min(y0, y1), max(y0, y1) + 1):
            d = tmp_path / "1" / str(tx)
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{ty}.png").write_bytes(b"not a png")
            poisoned += 1

    fetch_region_terrarium(*_BBOX, 8, 8, zoom=1, cache_dir=tmp_path)
    assert client.calls == poisoned


def test_terrarium_cache_failed_publish_leaves_no_tmp_orphan(monkeypatch, tmp_path):
    """A failed cache publish must not strand its pid-scoped .tmp file.

    The temp name embeds the pid, so orphans from failed runs would otherwise
    accumulate in a long-lived cache directory with nothing to sweep them.
    """
    d = tmp_path / "1" / "0"
    d.mkdir(parents=True)

    def failing_replace(src: object, dst: object, **kw: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", failing_replace)
    _store_tile(tmp_path, 1, 0, 0, _tile_png())

    leftovers = [p for p in d.iterdir() if p.name.endswith(".tmp")]
    assert not leftovers, f"stranded temp files: {leftovers}"
