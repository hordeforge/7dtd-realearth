"""Behavior of the `realearth serve` static handler (gzip + revalidation)."""

import functools
import gzip
import http.server
import threading
from pathlib import Path

import httpx
import pytest

from realearth import viewer_server
from realearth.viewer_server import ViewerHandler

BIG_HTML = b"<html>" + b"x" * 4096 + b"</html>"
SMALL_TXT = b"tiny\n"
PNG_BYTES = bytes(range(256)) * 64  # binary, incompressible-ish, .png suffix


@pytest.fixture()
def served_root(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_bytes(BIG_HTML)
    (tmp_path / "tiny.txt").write_bytes(SMALL_TXT)
    (tmp_path / "tile.png").write_bytes(PNG_BYTES)
    return tmp_path


@pytest.fixture()
def server(served_root: Path):
    tmp_path = served_root

    handler = functools.partial(ViewerHandler, directory=str(tmp_path))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base
    httpd.shutdown()
    httpd.server_close()


def test_text_served_gzipped_when_accepted(server: str):
    res = httpx.get(f"{server}/index.html", headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert res.headers["Content-Encoding"] == "gzip"
    # httpx decodes transparently; a gzipped transfer is far smaller than raw,
    # and the body still round-trips to the original file contents.
    assert int(res.headers["Content-Length"]) < len(BIG_HTML)
    assert res.content == BIG_HTML
    assert "Accept-Encoding" in res.headers["Vary"]
    assert res.headers["Cache-Control"] == "no-cache"


def test_uncompressed_when_client_does_not_accept(server: str):
    res = httpx.get(f"{server}/index.html", headers={"Accept-Encoding": "identity"})
    assert res.status_code == 200
    assert "Content-Encoding" not in res.headers
    assert res.content == BIG_HTML


def test_already_compressed_formats_pass_through(server: str):
    res = httpx.get(f"{server}/tile.png", headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert "Content-Encoding" not in res.headers
    assert res.content == PNG_BYTES


def test_tiny_files_skip_compression(server: str):
    res = httpx.get(f"{server}/tiny.txt", headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert "Content-Encoding" not in res.headers
    assert res.content == SMALL_TXT


def test_if_modified_since_answers_304(server: str):
    first = httpx.get(f"{server}/index.html", headers={"Accept-Encoding": "gzip"})
    last_modified = first.headers["Last-Modified"]
    second = httpx.get(
        f"{server}/index.html",
        headers={"Accept-Encoding": "gzip", "If-Modified-Since": last_modified},
    )
    assert second.status_code == 304


def test_etag_answers_304_for_every_encoding(server: str):
    # A validator must cover the gzip and the identity representation, or a
    # client that negotiated the other encoding re-downloads the whole file.
    for accept in ("gzip", "identity"):
        first = httpx.get(f"{server}/index.html", headers={"Accept-Encoding": accept})
        etag = first.headers["ETag"]
        second = httpx.get(
            f"{server}/index.html",
            headers={"Accept-Encoding": accept, "If-None-Match": etag},
        )
        assert second.status_code == 304, accept
        assert second.content == b"", accept


def test_stale_etag_is_replaced_not_304(server: str, served_root: Path):
    page = served_root / "index.html"
    res = httpx.get(f"{server}/index.html", headers={"Accept-Encoding": "gzip"})
    page.write_bytes(BIG_HTML + b"y" * 2048)
    again = httpx.get(
        f"{server}/index.html",
        headers={"Accept-Encoding": "gzip", "If-None-Match": res.headers["ETag"]},
    )
    assert again.status_code == 200
    assert again.content == BIG_HTML + b"y" * 2048


def test_if_none_match_beats_if_modified_since(server: str):
    res = httpx.get(f"{server}/index.html", headers={"Accept-Encoding": "gzip"})
    mismatched = httpx.get(
        f"{server}/index.html",
        headers={
            "Accept-Encoding": "gzip",
            "If-None-Match": 'W/"deadbeef-1"',
            "If-Modified-Since": res.headers["Last-Modified"],
        },
    )
    assert mismatched.status_code == 200


def test_gzip_body_is_compressed_once_per_revision(server: str, monkeypatch):
    calls = 0
    real = gzip.compress

    def counting(data: bytes, compresslevel: int = -1) -> bytes:
        nonlocal calls
        calls += 1
        return real(data, compresslevel=compresslevel)

    monkeypatch.setattr(gzip, "compress", counting)
    viewer_server.gzip_body.cache_clear()
    for _ in range(5):
        res = httpx.get(f"{server}/index.html", headers={"Accept-Encoding": "gzip"})
        assert res.status_code == 200
        assert res.content == BIG_HTML
    assert calls <= 1


def test_security_headers_allow_no_remote_script_origin(server: str):
    # three.js is served from the vendored copy, so the served CSP must not
    # whitelist a third-party origin: a remote script-src entry is a remote
    # code-execution path into the viewer origin.
    res = httpx.get(f"{server}/index.html", headers={"Accept-Encoding": "identity"})
    csp = res.headers["Content-Security-Policy"]
    assert "https://" not in csp
    assert "'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"


def test_connections_are_reused_across_assets(server: str):
    # One page load fetches many files; HTTP/1.0 would open a socket per asset.
    with httpx.Client() as client:
        first = client.get(f"{server}/index.html", headers={"Accept-Encoding": "gzip"})
        second = client.get(f"{server}/tiny.txt", headers={"Accept-Encoding": "gzip"})
    assert first.http_version == "HTTP/1.1"
    assert second.http_version == "HTTP/1.1"
    assert first.extensions["network_stream"] is second.extensions["network_stream"]


def test_conditional_get_keeps_the_connection_open(server: str):
    first = httpx.get(f"{server}/index.html", headers={"Accept-Encoding": "gzip"})
    with httpx.Client() as client:
        fresh = client.get(
            f"{server}/index.html",
            headers={"Accept-Encoding": "gzip", "If-None-Match": first.headers["ETag"]},
        )
        after = client.get(f"{server}/tiny.txt")
    # A bodyless 304 must still frame the persistent connection, or the next
    # request on it is read as the tail of a body that never ends.
    assert fresh.status_code == 304
    assert after.status_code == 200
    assert after.content == SMALL_TXT


def test_parallel_requests_are_concurrent(server: str):
    paths = ["/index.html", "/tiny.txt", "/tile.png"] * 4
    responses: list[httpx.Response] = []
    errors: list[Exception] = []

    def fetch(path: str) -> None:
        try:
            responses.append(httpx.get(f"{server}{path}", headers={"Accept-Encoding": "gzip"}))
        # Broad catch is deliberate: any transport failure is collected and
        # asserted below, so the test reports it instead of the thread dying.
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=fetch, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(responses) == len(paths)
    assert all(r.status_code == 200 for r in responses)
