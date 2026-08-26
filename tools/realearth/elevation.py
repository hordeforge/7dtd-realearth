"""Elevation data sources.

- open_meteo: free HTTP API, good for small demo regions
- synthetic: procedural hills for offline tests without network
- terrarium_url: helper for AWS Terrain Tiles / Mapzen Terrarium PNG decoding
- geotiff: optional rasterio path when `gis` extras are installed
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path

import httpx
import numpy as np

from realearth import JsonDict

# Bounded retry for idempotent tile/batch GETs: one 503 from the tile host would
# otherwise abort an entire multi-hundred-tile region build.
_MAX_ATTEMPTS = 3


def _get_with_retry(
    client: httpx.Client, url: str, *, params: JsonDict | None = None
) -> httpx.Response:
    """GET with bounded deterministic backoff for transient failures (transport errors, 429, 5xx).

    Client errors (other than 429) are not retried: they will fail identically.
    Backoff is a fixed schedule with no jitter: this pipeline is a sequential
    batch fetcher (no thundering herd to spread), and unseeded RNG here would
    make retry timing irreproducible run-to-run.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            r = client.get(url, params=params)
            if r.status_code < 500 and r.status_code != 429:
                r.raise_for_status()
                return r
            last_exc = httpx.HTTPStatusError(
                f"HTTP {r.status_code} for {url}", request=r.request, response=r
            )
        except httpx.TransportError as e:
            last_exc = e
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(min(8.0, 0.5 * (2**attempt)))
    assert last_exc is not None
    raise last_exc


def sample_open_meteo(
    lons: np.ndarray,
    lats: np.ndarray,
    *,
    batch: int = 100,
    timeout: float = 60.0,
) -> np.ndarray:
    """Sample elevation (m) at lon/lat points via Open-Meteo Elevation API.

    API: https://api.open-meteo.com/v1/elevation
    Rate limits apply; use only for small regions / demos.
    """
    lons_f = np.asarray(lons, dtype=np.float64).ravel()
    lats_f = np.asarray(lats, dtype=np.float64).ravel()
    if lons_f.shape != lats_f.shape:
        raise ValueError("lons/lats shape mismatch")
    out = np.zeros(lons_f.shape[0], dtype=np.float32)

    with httpx.Client(timeout=timeout) as client:
        for i in range(0, lons_f.shape[0], batch):
            sl = slice(i, i + batch)
            params = {
                "latitude": ",".join(f"{v:.5f}" for v in lats_f[sl]),
                "longitude": ",".join(f"{v:.5f}" for v in lons_f[sl]),
            }
            r = _get_with_retry(
                client, "https://api.open-meteo.com/v1/elevation", params=params
            )
            data = r.json()
            elev = data.get("elevation")
            if elev is None:
                raise RuntimeError(f"unexpected elevation response: {data}")
            out[sl] = np.asarray(elev, dtype=np.float32)

    return out


def grid_lonlat(
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Meshgrid of lon/lat for a regular equirectangular patch (pixel centers)."""
    if east <= west or north <= south:
        raise ValueError("invalid bbox")
    xs = np.linspace(west, east, width, endpoint=False) + (east - west) / width / 2
    ys = (
        np.linspace(north, south, height, endpoint=False) + (south - north) / height / 2
    )
    # ys goes north→south so row 0 is north (matches Z increase southward)
    lon, lat = np.meshgrid(xs, ys)
    return lon, lat


def fetch_region_open_meteo(
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
    *,
    max_points: int = 40_000,
) -> np.ndarray:
    """Fetch a rectangular elevation grid. Downsamples if larger than max_points."""
    n = width * height
    if n > max_points:
        # fetch coarser grid then upsample
        scale = math.sqrt(n / max_points)
        w2 = max(8, int(width / scale))
        h2 = max(8, int(height / scale))
        lon, lat = grid_lonlat(west, south, east, north, w2, h2)
        coarse = sample_open_meteo(lon, lat).reshape(h2, w2)
        return _resize_nearest(coarse, height, width)

    lon, lat = grid_lonlat(west, south, east, north, width, height)
    return sample_open_meteo(lon, lat).reshape(height, width)


def decode_terrarium_png(rgb: np.ndarray) -> np.ndarray:
    """Decode Mapzen Terrarium RGB elevation encoding to meters ASL.

    elevation = (R * 256 + G + B / 256) - 32768
    """
    rgb = np.asarray(rgb)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError("expected HxWx3 RGB image")
    r = rgb[:, :, 0].astype(np.float64)
    g = rgb[:, :, 1].astype(np.float64)
    b = rgb[:, :, 2].astype(np.float64)
    return (r * 256.0 + g + b / 256.0) - 32768.0


# AWS Open Data terrain tiles (Mapzen Terrarium encoding). Not Google data.
TERRARIUM_URL = (
    "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
)


def terrarium_cache_dir() -> Path | None:
    """Cache root from RE_TERRARIUM_CACHE; unset or empty disables caching."""
    v = os.environ.get("RE_TERRARIUM_CACHE", "").strip()
    return Path(v) if v else None


def _cached_tile(cache_dir: Path, zoom: int, tx: int, ty: int) -> bytes | None:
    path = cache_dir / str(zoom) / str(tx) / f"{ty}.png"
    try:
        return path.read_bytes()
    except OSError:
        return None


def _store_tile(cache_dir: Path, zoom: int, tx: int, ty: int, data: bytes) -> None:
    """Publish a fetched tile into the cache atomically (best effort).

    The cache is the only local copy of source tiles: if the remote dataset
    disappears, packs can only be rebuilt from what was persisted here.
    """
    directory = cache_dir / str(zoom) / str(tx)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / f".{ty}.{os.getpid()}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, directory / f"{ty}.png")
    except OSError:
        pass


def _decode_tile_png(data: bytes) -> np.ndarray | None:
    """Decode PNG bytes to terrarium meters; None if unreadable (corrupt cache)."""
    from io import BytesIO

    from PIL import Image

    try:
        img = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return None
    return decode_terrarium_png(np.asarray(img)).astype(np.float32)


def _lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    """Web Mercator tile indices for lon/lat at zoom z."""
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y


def fetch_region_terrarium(
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
    *,
    zoom: int = 10,
    timeout: float = 60.0,
    max_workers: int = 8,
    cache_dir: Path | str | None = None,
) -> np.ndarray:
    """Fetch real elevation via open AWS Terrarium tiles, resample to width×height.

    Free open terrain tiles (not Google). Suitable for regional realism.
    Higher zoom = more detail (and more HTTP requests). Tile downloads run on a
    small thread pool; each tile decodes into a disjoint mosaic window.

    cache_dir: optional local tile cache. When set, tiles are served from disk
    when present and every fetched tile is stored there, so packs stay
    rebuildable offline if the remote dataset changes or disappears. Defaults
    to RE_TERRARIUM_CACHE (unset = no caching).
    """
    from concurrent.futures import ThreadPoolExecutor

    if cache_dir is None:
        cache_dir = terrarium_cache_dir()
    cache = Path(cache_dir) if cache_dir is not None else None

    zoom = max(0, min(15, int(zoom)))
    n = 2**zoom
    x0, y0 = _lonlat_to_tile(west, north, zoom)  # north → smaller y
    x1, y1 = _lonlat_to_tile(east, south, zoom)
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    # clamp span
    x0, x1 = max(0, x0), min(n - 1, x1)
    y0, y1 = max(0, y0), min(n - 1, y1)

    tile_px = 256
    mosaic_w = (x1 - x0 + 1) * tile_px
    mosaic_h = (y1 - y0 + 1) * tile_px
    mosaic = np.full((mosaic_h, mosaic_w), np.nan, dtype=np.float32)

    def fetch_tile(ty: int, tx: int) -> tuple[int, int, np.ndarray]:
        if cache is not None:
            data = _cached_tile(cache, zoom, tx, ty)
            if data is not None:
                elev = _decode_tile_png(data)
                if elev is not None:
                    return ty, tx, elev
        url = TERRARIUM_URL.format(z=zoom, x=tx, y=ty)
        r = _get_with_retry(client, url)
        if cache is not None:
            _store_tile(cache, zoom, tx, ty, r.content)
        elev = _decode_tile_png(r.content)
        if elev is None:
            raise ValueError(f"undecodable tile PNG from {url}")
        return ty, tx, elev

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        tiles = [(ty, tx) for ty in range(y0, y1 + 1) for tx in range(x0, x1 + 1)]
        workers = max(1, min(max_workers, len(tiles)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # Propagate the first failure like the sequential loop did (raise_for_status).
            for ty, tx, elev in pool.map(lambda t: fetch_tile(t[0], t[1]), tiles):
                py = (ty - y0) * tile_px
                px = (tx - x0) * tile_px
                mosaic[py : py + tile_px, px : px + tile_px] = elev

    # Crop mosaic to exact lon/lat bbox within the tile range
    def lon_to_px(lon: float) -> float:
        return (lon + 180.0) / 360.0 * n * tile_px - x0 * tile_px

    def lat_to_py(lat: float) -> float:
        lat = max(min(lat, 85.05112878), -85.05112878)
        lat_rad = math.radians(lat)
        merc_y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0
        return merc_y * n * tile_px - y0 * tile_px

    left = max(0, int(lon_to_px(west)))
    right = min(mosaic_w, int(math.ceil(lon_to_px(east))))
    top = max(0, int(lat_to_py(north)))
    bottom = min(mosaic_h, int(math.ceil(lat_to_py(south))))
    crop = mosaic if right <= left or bottom <= top else mosaic[top:bottom, left:right]
    # Fill any nan with neighbor mean
    if np.isnan(crop).any():
        fill = float(np.nanmean(crop)) if np.isfinite(crop).any() else 0.0
        crop = np.where(np.isnan(crop), fill, crop)
    return _resize_linear(crop.astype(np.float64), height, width).astype(np.float32)


def fetch_region_geotiff(
    path: Path,
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
) -> np.ndarray:
    """Sample a GeoTIFF DEM into an equirectangular width×height grid (needs rasterio)."""
    try:
        import rasterio
        from rasterio.warp import transform as rio_transform
    except ImportError as e:
        raise ImportError("install realearth-tools[gis] for GeoTIFF support") from e

    lon, lat = grid_lonlat(west, south, east, north, width, height)
    with rasterio.open(path) as ds:
        # Transform WGS84 lon/lat to dataset CRS if needed
        if ds.crs and str(ds.crs) not in ("EPSG:4326", "OGC:CRS84"):
            xs, ys = rio_transform(
                "EPSG:4326", ds.crs, lon.ravel().tolist(), lat.ravel().tolist()
            )
            xs = np.asarray(xs).reshape(lon.shape)
            ys = np.asarray(ys).reshape(lat.shape)
        else:
            xs, ys = lon, lat
        samples = list(ds.sample(zip(xs.ravel(), ys.ravel(), strict=True)))
        vals = np.array([s[0] for s in samples], dtype=np.float32).reshape(
            height, width
        )
        if ds.nodata is not None:
            vals = np.where(vals == ds.nodata, np.nan, vals)
        if np.isnan(vals).any():
            fill = float(np.nanmean(vals)) if np.isfinite(vals).any() else 0.0
            vals = np.where(np.isnan(vals), fill, vals)
    return vals


def synthetic_elevation(
    width: int,
    height: int,
    *,
    seed: int = 42,
    base: float = 120.0,
    peak: float = 900.0,
    sea_fraction: float = 0.15,
) -> np.ndarray:
    """Procedural elevation for offline tests (no network)."""
    rng = np.random.default_rng(seed)
    # multi-octave value noise via upsampled random grids
    acc = np.zeros((height, width), dtype=np.float64)
    amp = 1.0
    total = 0.0
    for octave in range(1, 6):
        gh = max(2, height // (2 ** (5 - octave)))
        gw = max(2, width // (2 ** (5 - octave)))
        grid = rng.random((gh, gw))
        acc += amp * _resize_linear(grid, height, width)
        total += amp
        amp *= 0.55
    n = acc / total
    elev = base + n * (peak - base)

    # Carve a simple coastline on the west edge
    xs = np.linspace(0, 1, width)
    coast = sea_fraction + 0.05 * np.sin(xs * 12)
    cuts = (coast * width).astype(np.int64)
    below = np.arange(width) < cuts
    if below.any():
        # One draw of (width, height) in C order yields each column's `height`
        # values in ascending-column order: identical sequence to the former
        # per-column rng.random(height) loop, without `width` strided writes.
        noise = rng.random((width, height))
        elev[:, below] = (-20.0 - 5.0 * noise[below]).T

    # Central ridge
    cy, cx = height // 2, int(width * 0.55)
    yy, xx = np.ogrid[:height, :width]
    ridge = np.exp(
        -(((yy - cy) / (height * 0.15)) ** 2 + ((xx - cx) / (width * 0.08)) ** 2)
    )
    elev += ridge * 600.0
    return elev.astype(np.float32)


def _resize_nearest(src: np.ndarray, h: int, w: int) -> np.ndarray:
    ys = (np.linspace(0, src.shape[0] - 1, h)).astype(np.int32)
    xs = (np.linspace(0, src.shape[1] - 1, w)).astype(np.int32)
    return src[ys][:, xs]


def _resize_linear(src: np.ndarray, h: int, w: int) -> np.ndarray:
    """Bilinear resize via Pillow (already a project dependency)."""
    from PIL import Image

    src = np.asarray(src, dtype=np.float32)
    if src.shape == (h, w):
        return src.astype(np.float64)
    img = Image.fromarray(src, mode="F")
    out = img.resize((w, h), resample=Image.Resampling.BILINEAR)
    return np.asarray(out, dtype=np.float64)
