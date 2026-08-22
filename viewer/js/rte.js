/**
 * Decode RealEarth .rte tiles (RTE1) in the browser.
 * Layout must match tools/realearth/tile_format.py
 */

const MAGIC = "RTE1";
const FLAG_POP = 0b001; // bit 0: population band present
const FLAG_LC = 0b010; // bit 1: landcover band present
const FLAG_POI = 0b100; // bit 2: point-of-interest JSON present
const ELEV_OFFSET = 11_000;

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
  if (bytes.length < 6) {
    throw new Error("zlib payload too short");
  }
  const raw = bytes.subarray(2, -4);
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
  const magic = String.fromCodePoint(u8[0], u8[1], u8[2], u8[3]);
  if (magic !== MAGIC) {
    throw new Error(`bad magic: ${magic}`);
  }

  let off = 4;
  const tileX = readI32(view, off);
  off += 4;
  const tileZ = readI32(view, off);
  off += 4;
  const version = readU16(view, off);
  off += 2;
  const flags = readU16(view, off);
  off += 2;
  const width = readU32(view, off);
  off += 4;
  const height = readU32(view, off);
  off += 4;
  // reserved field, not used by RTE1
  off += 4;

  const elevLen = readU32(view, off);
  off += 4;
  const elevZ = u8.subarray(off, off + elevLen);
  off += elevLen;
  const elevRaw = await inflateZlib(elevZ);
  const elevU16 = new Uint16Array(elevRaw.buffer, elevRaw.byteOffset, width * height);
  const elevation = new Float32Array(width * height);
  for (let i = 0; i < elevation.length; i += 1) {
    elevation[i] = elevU16[i] - ELEV_OFFSET;
  }

  const land = await readBand(u8, view, flags, FLAG_LC, off);
  const landcover = land ? land.bytes : null;
  off = land ? land.nextOff : off;
  const pop = await readBand(u8, view, flags, FLAG_POP, off);
  const population = pop ? pop.bytes : null;
  off = pop ? pop.nextOff : off;
  let poiJson = "";
  if ((flags & FLAG_POI) !== 0 && off < u8.length) {
    const n = readU32(view, off);
    poiJson = new TextDecoder().decode(u8.subarray(off + 4, off + 4 + n));
  }

  return { tileX, tileZ, version, width, height, elevation, landcover, population, poiJson };
}

/**
 * Inflate one optional band (landcover/population) when its flag bit is set.
 * Returns null when the band is absent, else the bytes and the next offset.
 */
async function readBand(u8, view, flags, flag, off) {
  if ((flags & flag) === 0) {
    return null;
  }
  const n = readU32(view, off);
  const raw = await inflateZlib(u8.subarray(off + 4, off + 4 + n));
  return { bytes: new Uint8Array(raw), nextOff: off + 4 + n };
}
