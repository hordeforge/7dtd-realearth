/**
 * Decode RealEarth .rte tiles (RTE1) in the browser.
 * Layout must match tools/realearth/tile_format.py
 */

const MAGIC = "RTE1";
const FLAG_POP = 1 << 0;
const FLAG_LC = 1 << 1;
const FLAG_POI = 1 << 2;
const ELEV_OFFSET = 11000;

function readI32(view, off) {
  return view.getInt32(off, true);
}
function readU16(view, off) {
  return view.getUint16(off, true);
}
function readU32(view, off) {
  return view.getUint32(off, true);
}

async function inflateZlib(bytes) {
  // zlib wrapper: skip CMF/FLG (2) and Adler32 (4)
  if (bytes.length < 6) throw new Error("zlib payload too short");
  const raw = bytes.subarray(2, bytes.length - 4);
  if (typeof DecompressionStream !== "undefined") {
    const ds = new DecompressionStream("deflate-raw");
    const stream = new Blob([raw]).stream().pipeThrough(ds);
    const ab = await new Response(stream).arrayBuffer();
    return new Uint8Array(ab);
  }
  throw new Error("DecompressionStream not available; use a modern browser");
}

/**
 * @param {ArrayBuffer} buffer
 */
export async function decodeRte(buffer) {
  const u8 = new Uint8Array(buffer);
  const view = new DataView(buffer);
  const magic = String.fromCharCode(u8[0], u8[1], u8[2], u8[3]);
  if (magic !== MAGIC) throw new Error(`bad magic: ${magic}`);

  let off = 4;
  const tileX = readI32(view, off); off += 4;
  const tileZ = readI32(view, off); off += 4;
  const version = readU16(view, off); off += 2;
  const flags = readU16(view, off); off += 2;
  const width = readU32(view, off); off += 4;
  const height = readU32(view, off); off += 4;
  off += 4; // reserved

  const elevLen = readU32(view, off); off += 4;
  const elevZ = u8.subarray(off, off + elevLen); off += elevLen;
  const elevRaw = await inflateZlib(elevZ);
  const elevU16 = new Uint16Array(elevRaw.buffer, elevRaw.byteOffset, width * height);
  const elevation = new Float32Array(width * height);
  for (let i = 0; i < elevation.length; i++) elevation[i] = elevU16[i] - ELEV_OFFSET;

  let landcover = null;
  let population = null;
  let poiJson = "";

  if (flags & FLAG_LC) {
    const n = readU32(view, off); off += 4;
    const raw = await inflateZlib(u8.subarray(off, off + n)); off += n;
    landcover = new Uint8Array(raw);
  }
  if (flags & FLAG_POP) {
    const n = readU32(view, off); off += 4;
    const raw = await inflateZlib(u8.subarray(off, off + n)); off += n;
    population = new Uint8Array(raw);
  }
  if ((flags & FLAG_POI) && off < u8.length) {
    const n = readU32(view, off); off += 4;
    poiJson = new TextDecoder().decode(u8.subarray(off, off + n));
  }

  return {
    tileX,
    tileZ,
    version,
    width,
    height,
    elevation,
    landcover,
    population,
    poiJson,
  };
}
