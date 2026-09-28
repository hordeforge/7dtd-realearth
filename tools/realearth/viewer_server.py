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
from typing import BinaryIO

# Level 6 rather than 9: on the 1.3 MB vendored three.js module it saves only
# ~2 KB over level 6's 268 KB while costing nearly twice the CPU, and level 1
# gives back 150 KB. The result is memoized, so this runs once per revision.
_GZIP_LEVEL = 6
# Distinct static assets a browser pulls in one session: the page, the CSS,
# the module graph, catalog/pack JSON, the vendored three.js.
_GZIP_CACHE_ENTRIES = 32


@functools.lru_cache(maxsize=_GZIP_CACHE_ENTRIES)
def gzip_body(path: str, mtime_ns: int, size: int) -> bytes:
    """Gzip `path` once per (mtime, size) revision and keep the bytes.

    Keying on the stat signature makes a rewritten file recompress, and gzip
    output is deterministic, so serving the memoized bytes to every later
    request is identical to recompressing them.
    """
    return gzip.compress(Path(path).read_bytes(), compresslevel=_GZIP_LEVEL)


def _etag_for(fstat: os.stat_result) -> str:
    """Weak validator for one file revision, shared by every content coding.

    Weak because the same revision is served as gzip or identity depending on
    Accept-Encoding; the bytes differ, the representation does not.
    """
    return f'W/"{fstat.st_mtime_ns:x}-{fstat.st_size:x}"'


class ViewerHandler(http.server.SimpleHTTPRequestHandler):
    """Static handler for the viewer: gzip for text assets + revalidation.

    Browsers fetch a pack as half a dozen parallel requests; stock
    SimpleHTTPRequestHandler sends every byte uncompressed and nothing marks
    the responses cacheable or not. This subclass gzips small text responses
    (HTML/CSS/JS/JSON/SVG), leaves already-compressed formats (PNG/JPEG/ZIP)
    alone so gzip never inflates their transfer time, and marks everything
    `no-cache` so regenerated packs revalidate via ETag/If-Modified-Since 304s
    instead of serving stale heuristically cached copies.

    Compressed bodies are memoized per (path, mtime, size) by `_gzip_body`,
    so a static asset is deflated once per revision instead of once per
    request: the vendored three.js module costs ~19 ms of CPU per gzip at
    level 6 and is re-requested on every page load.
    """

    # Text formats that shrink under gzip. Images/archives are excluded: they
    # are stored compressed and gzip only wastes CPU on top of that.
    _COMPRESSIBLE_SUFFIXES = frozenset(
        {
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
        }
    )
    _MIN_COMPRESS_BYTES = 1024

    def log_message(self, format: str, *args: object) -> None:
        # skip boring 200s; sanitize control chars to block log injection via crafted paths
        if len(args) >= 2 and str(args[1]).startswith("2"):
            return
        safe_args = tuple(
            (str(a).replace("\r", "\\r").replace("\n", "\\n") if isinstance(a, str) else a)
            for a in args
        )
        super().log_message(format, *safe_args)

    def end_headers(self) -> None:
        # Content varies with what the client accepts; dev data changes between
        # runs, so always revalidate (cheap via ETag/Last-Modified 304s).
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", "no-cache")
        # Hardening: viewer serves only static packs, no framing or MIME sniffing.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            # No remote script origin: three.js is served from the vendored
            # copy under viewer/vendor/three, so script-src needs only 'self'.
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'",
        )
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        super().end_headers()

    def list_directory(self, path: str) -> None:  # type: ignore[override]
        # Disable directory listings: viewer has explicit catalog.json / viewer.json.
        self.send_error(http.HTTPStatus.NOT_FOUND, "Not Found")
        return

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

    def send_head(self) -> io.BytesIO | BinaryIO | None:
        """As the stdlib handler does: an open binary stream, or None after an error response."""
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
        if os.path.isdir(path):
            # Directory handling (trailing-slash redirect) stays stock.
            return super().send_head()
        try:
            fstat = os.stat(path)
        except OSError:
            return super().send_head()
        if not os.path.isfile(path):
            # Sockets, FIFOs and devices are not static assets.
            return super().send_head()
        suffix = os.path.splitext(path)[1].lower()
        compress = (
            "gzip" in accept.lower()
            and suffix in self._COMPRESSIBLE_SUFFIXES
            and fstat.st_size >= self._MIN_COMPRESS_BYTES
        )
        etag = _etag_for(fstat)
        if self._client_copy_is_fresh(etag, fstat.st_mtime):
            self.send_response(http.HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", self.date_time_string(int(fstat.st_mtime)))
            self.end_headers()
            return None
        try:
            if compress:
                payload = gzip_body(path, fstat.st_mtime_ns, fstat.st_size)
            else:
                payload = Path(path).read_bytes()
        except OSError:
            return super().send_head()
        self.send_response(http.HTTPStatus.OK)
        self.send_header("Content-Type", self.guess_type(path) or "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        if compress:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", self.date_time_string(int(fstat.st_mtime)))
        self.end_headers()
        if self.command == "HEAD":
            return None
        return io.BytesIO(payload)

    def _client_copy_is_fresh(self, etag: str, mtime: float) -> bool:
        """True when the client already holds this revision (RFC 9110 13.1.3).

        If-None-Match wins outright when present: an If-Modified-Since that
        says "not modified" must not override a tag that says otherwise.
        """
        if_none_match = self.headers.get("If-None-Match")
        if if_none_match is not None:
            return if_none_match.strip() == etag
        return not self._stale_client_copy(self.headers.get("If-Modified-Since"), mtime)


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
