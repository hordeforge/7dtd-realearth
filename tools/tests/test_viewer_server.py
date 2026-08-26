"""Behavior of the `realearth serve` static handler (gzip + revalidation)."""

import functools
import http.server
import threading
from pathlib import Path

import httpx
import pytest

from realearth.viewer_server import ViewerHandler

BIG_HTML = b"<html>" + b"x" * 4096 + b"</html>"
SMALL_TXT = b"tiny\n"
PNG_BYTES = bytes(range(256)) * 64  # binary, incompressible-ish, .png suffix


@pytest.fixture()
def server(tmp_path: Path):
    (tmp_path / "index.html").write_bytes(BIG_HTML)
    (tmp_path / "tiny.txt").write_bytes(SMALL_TXT)
    (tmp_path / "tile.png").write_bytes(PNG_BYTES)

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


def test_parallel_requests_are_concurrent(server: str):
    paths = ["/index.html", "/tiny.txt", "/tile.png"] * 4
    responses: list[httpx.Response] = []
    errors: list[Exception] = []

    def fetch(path: str) -> None:
        try:
            responses.append(
                httpx.get(f"{server}{path}", headers={"Accept-Encoding": "gzip"})
            )
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
