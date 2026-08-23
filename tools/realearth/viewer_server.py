"""Static file server for the web map viewer (`realearth serve`)."""

from __future__ import annotations

import contextlib
import email.utils
import functools
import gzip
import http.server
import io
import os
import webbrowser
from pathlib import Path


class ViewerHandler(http.server.SimpleHTTPRequestHandler):
    """Static handler for the viewer: gzip for text assets + revalidation.

    Browsers fetch a pack as half a dozen parallel requests; stock
    SimpleHTTPRequestHandler sends every byte uncompressed and nothing marks
    the responses cacheable or not. This subclass gzips small text responses
    (HTML/CSS/JS/JSON/SVG), leaves already-compressed formats (PNG/JPEG/ZIP)
    alone so gzip never inflates their transfer time, and marks everything
    `no-cache` so regenerated packs revalidate via If-Modified-Since 304s
    instead of serving stale heuristically cached copies.
    """

    # Text formats that shrink under gzip. Images/archives are excluded: they
    # are stored compressed and gzip only wastes CPU on top of that.
    _COMPRESSIBLE_SUFFIXES = frozenset({
        ".html",
        ".htm",
        ".css",
        ".js",
        ".mjs",
        ".json",
        ".svg",
        ".map",
        ".txt",
        ".xml",
        ".csv",
    })
    _MIN_COMPRESS_BYTES = 1024

    def log_message(self, format: str, *args: object) -> None:
        # skip boring 200s; sanitize control chars to block log injection via crafted paths
        if len(args) >= 2 and str(args[1]).startswith("2"):
            return
        safe_args = tuple(
            str(a).replace("\r", "\\r").replace("\n", "\\n") if isinstance(a, str) else a
            for a in args
        )
        super().log_message(format, *safe_args)

    def end_headers(self) -> None:
        # Content varies with what the client accepts; dev data changes between
        # runs, so always revalidate (cheap via Last-Modified/304).
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", "no-cache")
        # Hardening: viewer serves only static packs, no framing or MIME sniffing.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; "
                         "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                         "style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data: blob:; "
                         "connect-src 'self'; "
                         "frame-ancestors 'none'")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        super().end_headers()

    def list_directory(self, path: str):  # type: ignore[override]
        # Disable directory listings: viewer has explicit catalog.json / viewer.json.
        self.send_error(http.HTTPStatus.NOT_FOUND, "Not Found")
        return None

    @staticmethod
    def _stale_client_copy(header_value: str | None, mtime: float) -> bool:
        """True when the client's cached copy is stale (stdlib semantics)."""
        if not header_value:
            return True
        try:
            since = email.utils.parsedate_to_datetime(header_value)
        except (TypeError, IndexError, OverflowError, ValueError):
            return True
        if since.tzinfo is None:
            return True
        return int(mtime) > since.timestamp()

    # No return annotation: this overrides stdlib's untyped
    # BaseHTTPRequestHandler.send_head.
    def send_head(self):
        accept = self.headers.get("Accept-Encoding", "")
        raw_path = self.translate_path(self.path)
        # Containment: translated path must remain inside the served directory.
        try:
            base = Path(self.directory).resolve()
            target = Path(raw_path).resolve()
            # Allow the directory itself; listing is blocked separately.
            if target != base and base not in target.parents:
                self.send_error(http.HTTPStatus.NOT_FOUND, "Not Found")
                return None
        except Exception:
            self.send_error(http.HTTPStatus.NOT_FOUND, "Not Found")
            return None
        path = raw_path
        suffix = os.path.splitext(path)[1].lower()
        if (
            "gzip" not in accept.lower()
            or os.path.isdir(path)
            or suffix not in self._COMPRESSIBLE_SUFFIXES
        ):
            return super().send_head()
        try:
            data = Path(path).read_bytes()
            fstat = os.stat(path)
        except OSError:
            return super().send_head()
        if len(data) < self._MIN_COMPRESS_BYTES:
            return super().send_head()
        if self._stale_client_copy(self.headers.get("If-Modified-Since"), fstat.st_mtime):
            payload = gzip.compress(data, compresslevel=6)
        else:
            self.send_response(http.HTTPStatus.NOT_MODIFIED)
            self.end_headers()
            return None
        self.send_response(http.HTTPStatus.OK)
        self.send_header("Content-Type", self.guess_type(path) or "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Last-Modified", self.date_time_string(int(fstat.st_mtime)))
        self.end_headers()
        if self.command == "HEAD":
            return None
        return io.BytesIO(payload)


def serve(port: int, bind: str, directory: Path, *, open_browser: bool = True) -> None:
    """Serve `directory` until interrupted."""
    handler = functools.partial(ViewerHandler, directory=str(directory))
    # ThreadingHTTPServer: browsers request pack artifacts in parallel; a bare
    # TCPServer would serialize them behind each other.
    with http.server.ThreadingHTTPServer((bind, port), handler) as httpd:
        url = f"http://{bind}:{port}/"
        print(f"RealEarth viewer at {url}")
        print(f"Serving {directory}")
        if open_browser:
            with contextlib.suppress(Exception):
                webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
