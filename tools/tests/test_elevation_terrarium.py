"""Unit tests for Terrarium decode, tile math, and HTTP retry (no network)."""

import httpx
import numpy as np
import pytest

from realearth.elevation import (
    _get_with_retry,
    _lonlat_to_tile,
    decode_terrarium_png,
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
