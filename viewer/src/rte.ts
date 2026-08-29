// In-browser .rte tile decoder.
//
// .rte is the RealEarth tile format (tools/realearth/tile_format.py):
//   28-byte header: <4siiHHIII> magic "RTE1", tx, tz, version, flags, w, h, reserved
//   then length-prefixed zlib sections:
//     elevation  u16 (sample = elev_m + 11000 offset)  [always]
//     landcover  u8  [flag 1]
//     population u8  [flag 2]
//     poi blob   bytes [flag 4]
// zlib sections are standard zlib (0x78 header), so the browser's native
// DecompressionStream("deflate") inflates them without a vendored library.

export const RTE_MAGIC = "RTE1";
// Elevation is stored as u16 with a +11000 m offset (signed meters ASL).
export const RTE_ELEV_OFFSET_M = 11_000;
const RTE_HEADER_BYTES = 28;
const RTE_MAGIC_BYTES = 4;
const U32_BYTES = 4;
const U16_BYTES = 2;
// Header layout (Python struct "<4siiHHIII"): magic(4s), tx(i), tz(i),
// version(H), flags(H), width(I), height(I), reserved(I).
const TX_OFFSET = 4;
const TZ_OFFSET = 8;
const VERSION_OFFSET = 12;
const FLAGS_OFFSET = 14;
const WIDTH_OFFSET = 16;
const HEIGHT_OFFSET = 20;
const HEADER_END = 28;
// u16 bit-shift widths.
const BYTE_BITS = 8;
const HALFWORD_BITS = 16;
const THREE_BYTES_BITS = 24;
const THIRD_BYTE_INDEX = 3;
const FLAG_HAS_LANDCOVER = 1;
const FLAG_HAS_POPULATION = 2;

export type RteHeader = {
  tx: number;
  tz: number;
  version: number;
  flags: number;
  width: number;
  height: number;
};

export type RteTile = {
  header: RteHeader;
  elevationM: Float32Array; // width*height, meters ASL (signed)
  landcover: Uint8Array | null;
  population: Uint8Array | null;
};

function readU32(bytes: Uint8Array, offset: number): number {
  return (
    (bytes[offset] ?? 0) |
    ((bytes[offset + 1] ?? 0) << BYTE_BITS) |
    ((bytes[offset + 2] ?? 0) << HALFWORD_BITS) |
    ((bytes[offset + THIRD_BYTE_INDEX] ?? 0) << THREE_BYTES_BITS)
  );
}

export function parseRteHeader(bytes: Uint8Array): RteHeader {
  if (bytes.length < HEADER_END) {
    throw new Error(`RTE header truncated (${bytes.length} < ${RTE_HEADER_BYTES})`);
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let magic = "";
  for (let i = 0; i < RTE_MAGIC_BYTES; i++) {
    magic += String.fromCodePoint(bytes[i] ?? 0);
  }
  if (magic !== RTE_MAGIC) {
    throw new Error(`Not an RTE tile (magic ${JSON.stringify(magic)})`);
  }
  return {
    tx: view.getInt32(TX_OFFSET, true),
    tz: view.getInt32(TZ_OFFSET, true),
    version: view.getUint16(VERSION_OFFSET, true),
    flags: view.getUint16(FLAGS_OFFSET, true),
    width: view.getUint32(WIDTH_OFFSET, true),
    height: view.getUint32(HEIGHT_OFFSET, true),
  };
}

async function inflateSection(bytes: Uint8Array, offset: number, expectedBytes: number): Promise<Uint8Array> {
  const sectionLength = readU32(bytes, offset);
  const section = bytes.slice(offset + U32_BYTES, offset + U32_BYTES + sectionLength);
  // DecompressionStream is available in all modern browsers; "deflate" matches
  // Python zlib.compress (zlib wrapper, not raw deflate).
  const stream = new Blob([section]).stream().pipeThrough(new DecompressionStream("deflate"));
  const inflated = new Uint8Array(await new Response(stream).arrayBuffer());
  if (inflated.length !== expectedBytes) {
    throw new Error(`RTE section size mismatch (${inflated.length} != ${expectedBytes})`);
  }
  return inflated;
}

export async function decodeRteTile(bytes: Uint8Array): Promise<RteTile> {
  const header = parseRteHeader(bytes);
  const samples = header.width * header.height;
  let offset = HEADER_END;

  const elevRaw = await inflateSection(bytes, offset, samples * U16_BYTES);
  offset += U32_BYTES + readU32(bytes, offset);
  const elevationM = new Float32Array(samples);
  const elevView = new DataView(elevRaw.buffer, elevRaw.byteOffset, elevRaw.byteLength);
  for (let i = 0; i < samples; i++) {
    elevationM[i] = elevView.getUint16(i * U16_BYTES, true) - RTE_ELEV_OFFSET_M;
  }

  let landcover: Uint8Array | null = null;
  if ((header.flags & FLAG_HAS_LANDCOVER) !== 0) {
    landcover = await inflateSection(bytes, offset, samples);
    offset += U32_BYTES + readU32(bytes, offset);
  }
  let population: Uint8Array | null = null;
  if ((header.flags & FLAG_HAS_POPULATION) !== 0) {
    population = await inflateSection(bytes, offset, samples);
  }
  return { header, elevationM, landcover, population };
}
