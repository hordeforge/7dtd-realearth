// Longitude wrap helpers for continuous Map2D pan across ±180.
// Mirrored from viewer/src/lonWrap.ts — keep both in sync.

export const LON_MIN = -180;
export const LON_SPAN = 360;
/** Float / exporter tolerance when detecting a full-planet lon span. */
export const LON_SPAN_EPSILON = 1e-6;

export type LonLatBbox = {
  west: number;
  south: number;
  east: number;
  north: number;
};

/** Fold longitude into [-180, 180). */
export function foldLon(lon: number): number {
  if (!Number.isFinite(lon)) {
    return LON_MIN;
  }
  const x = ((lon - LON_MIN) % LON_SPAN + LON_SPAN) % LON_SPAN;
  return x + LON_MIN;
}

/**
 * True when the bbox is a full-planet (or near-full) longitude strip that
 * should tile horizontally for Google Maps-style continuous pan.
 * Regional packs with east > west stay non-wrapping.
 */
export function isFullPlanetLonBbox(west: number, east: number): boolean {
  if (!Number.isFinite(west) || !Number.isFinite(east)) {
    return false;
  }
  const span = east - west;
  // Full Earth export is typically west=-180 east=180 (span 360).
  // Allow a small epsilon for float / exporter rounding.
  return span >= LON_SPAN - LON_SPAN_EPSILON;
}

/**
 * Map lon into [0, 1) U over a wrapping full-planet bbox, or linear U for
 * regional packs. Returns null when lat is outside north/south.
 */
export function lonLatToUV(
  lon: number,
  lat: number,
  bbox: LonLatBbox
): { u: number; v: number } | null {
  const { west, south, east, north } = bbox;
  if (!Number.isFinite(lat) || north <= south) {
    return null;
  }
  if (lat > north || lat < south) {
    return null;
  }
  const v = (north - lat) / (north - south);
  if (isFullPlanetLonBbox(west, east)) {
    const wrapped = foldLon(lon);
    // Map [-180,180) onto [0,1) relative to west (usually -180).
    let u = (wrapped - west) / LON_SPAN;
    u = ((u % 1) + 1) % 1;
    return { u, v };
  }
  if (east <= west) {
    return null;
  }
  const u = (lon - west) / (east - west);
  if (u < 0 || u > 1) {
    return null;
  }
  return { u, v };
}

export type ImagePixel = {
  ix: number;
  iy: number;
  width: number;
  height: number;
};

/**
 * Inverse of lonLatToUV for image pixel coords. When wrap is on and ix is
 * outside [0, width), fold into the primary tile and still report lon.
 */
export function imageToLonLat(
  pixel: ImagePixel,
  bbox: LonLatBbox
): { lon: number; lat: number; u: number; v: number } | null {
  const { ix, iy, width, height } = pixel;
  const { west, south, east, north } = bbox;
  if (width <= 0 || height <= 0 || north <= south) {
    return null;
  }
  const wrap = isFullPlanetLonBbox(west, east);
  let u = ix / width;
  const v = iy / height;
  if (v < 0 || v > 1) {
    return null;
  }
  if (wrap) {
    u = ((u % 1) + 1) % 1;
    const lon = foldLon(west + u * LON_SPAN);
    const lat = north - v * (north - south);
    return { lon, lat, u, v };
  }
  if (east <= west || u < 0 || u > 1) {
    return null;
  }
  return {
    lon: west + u * (east - west),
    lat: north - v * (north - south),
    u,
    v,
  };
}

export type WrapView = {
  tx: number;
  scale: number;
  imageWidth: number;
  viewportWidth: number;
};

/**
 * How many horizontal tile copies to draw so the viewport is covered when
 * pan translation tx and scale place the camera over a wrapping world.
 * Returns start/end tile indices inclusive (e.g. -1..1).
 */
export function wrapTileRange(view: WrapView): { start: number; end: number } {
  const { tx, scale, imageWidth, viewportWidth } = view;
  if (imageWidth <= 0 || scale <= 0 || viewportWidth <= 0) {
    return { start: 0, end: 0 };
  }
  // Visible image-X range in world (tile) space.
  const left = -tx / scale;
  const right = (viewportWidth - tx) / scale;
  const start = Math.floor(left / imageWidth) - 1;
  const end = Math.ceil(right / imageWidth) + 1;
  // Cap runaway pan so we never draw thousands of copies.
  const maxTiles = 8;
  if (end - start > maxTiles) {
    const mid = Math.round((start + end) / 2);
    return { start: mid - Math.floor(maxTiles / 2), end: mid + Math.floor(maxTiles / 2) };
  }
  return { start, end };
}
