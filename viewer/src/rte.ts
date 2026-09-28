// In-browser .rte tile decoder.
//
// .rte is the RealEarth tile format (tools/realearth/tile_format.py):
//   28-byte header: <4siiHHIII> magic "RTE1", tx, tz, version, flags, w, h, reserved
//   then length-prefixed zlib sections:
//     elevation  u16 (sample = elev_m + 11000 offset)  [always]
//     landcover  u8  [flag bit 1]
//     population u8  [flag bit 0]
//     poi blob   bytes [flag bit 2] (not decoded here; the viewer does not use it)
// zlib sections are standard zlib (0x78 header), so the browser's native
// DecompressionStream("deflate") inflates them without a vendored library.

import { readCapped } from "./cappedStream.js";

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
// Flag bit positions as written by tile_format.py: FLAG_HAS_POPULATION = 1 << 0,
// FLAG_HAS_LANDCOVER = 1 << 1, FLAG_HAS_POI = 1 << 2.
const FLAG_HAS_POPULATION = 1;
const FLAG_HAS_LANDCOVER = 2;
// Wire format this decoder understands (tools/realearth/tile_format.py
// FORMAT_VERSION, Source/RealEarth/RteTile.cs FormatVersion).
export const RTE_FORMAT_VERSION = 1;
// A header claiming more samples than this would size the Float32Array below
// from attacker-controlled dimensions. Same ceiling the C# decoder enforces
// (RteTile.MaxTileSamples); real packs use 512x512 tiles.
const MAX_TILE_EDGE = 4096;
export const RTE_MAX_TILE_SAMPLES = MAX_TILE_EDGE * MAX_TILE_EDGE;

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
  // >>> 0 keeps the unsigned value: the shifts below are 32-bit signed, so
  // 0xffffffff would otherwise read back as -1 and slip past a bounds check.
  return (
    ((bytes[offset] ?? 0) |
      ((bytes[offset + 1] ?? 0) << BYTE_BITS) |
      ((bytes[offset + 2] ?? 0) << HALFWORD_BITS) |
      ((bytes[offset + THIRD_BYTE_INDEX] ?? 0) << THREE_BYTES_BITS)) >>>
    0
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

// Read one length-prefixed zlib section at `offset`, inflating it under a hard
// output cap so a section that inflates to far more than its header claims (a
// decompression bomb) is cancelled at the first chunk past the cap. Returns the
// inflated bytes and the offset of the next section.
async function readSection(
  bytes: Uint8Array,
  offset: number,
  expectedBytes: number
): Promise<{ data: Uint8Array; nextOffset: number }> {
  if (offset + U32_BYTES > bytes.length) {
    throw new Error("RTE section header truncated");
  }
  const sectionLength = readU32(bytes, offset);
  const start = offset + U32_BYTES;
  const end = start + sectionLength;
  if (sectionLength > bytes.length - start) {
    throw new Error(`RTE section length out of range (${sectionLength})`);
  }
  const section = bytes.slice(start, end);
  // DecompressionStream is available in all modern browsers; "deflate" matches
  // Python zlib.compress (zlib wrapper, not raw deflate).
  const stream = new Blob([section]).stream().pipeThrough(new DecompressionStream("deflate"));
  const data = await readCapped(stream, expectedBytes, `RTE section at offset ${offset}`);
  if (data.length !== expectedBytes) {
    throw new Error(`RTE section size mismatch (${data.length} != ${expectedBytes})`);
  }
  return { data, nextOffset: end };
}

export async function decodeRteTile(bytes: Uint8Array): Promise<RteTile> {
  const header = parseRteHeader(bytes);
  if (header.version > RTE_FORMAT_VERSION) {
    // Fail closed on future formats, as the Python and C# decoders do: a v2
    // layout change read as v1 turns into garbage terrain, not an error.
    throw new Error(
      `unsupported tile version: ${header.version} (max ${RTE_FORMAT_VERSION})`
    );
  }
  const samples = header.width * header.height;
  // Mirrors RteTile.cs MaxTileSamples: a corrupt or hostile header otherwise
  // allocates width*height floats (65535 x 65535 = 4.3e9) before failing opaquely.
  if (header.width <= 0 || header.height <= 0 || samples > RTE_MAX_TILE_SAMPLES) {
    throw new Error(`tile dims out of range: ${header.width}x${header.height}`);
  }

  const elev = await readSection(bytes, HEADER_END, samples * U16_BYTES);
  const elevationM = new Float32Array(samples);
  const elevView = new DataView(elev.data.buffer, elev.data.byteOffset, elev.data.byteLength);
  for (let i = 0; i < samples; i++) {
    elevationM[i] = elevView.getUint16(i * U16_BYTES, true) - RTE_ELEV_OFFSET_M;
  }

  let offset = elev.nextOffset;
  let landcover: Uint8Array | null = null;
  if ((header.flags & FLAG_HAS_LANDCOVER) !== 0) {
    const section = await readSection(bytes, offset, samples);
    landcover = section.data;
    offset = section.nextOffset;
  }
  let population: Uint8Array | null = null;
  if ((header.flags & FLAG_HAS_POPULATION) !== 0) {
    population = (await readSection(bytes, offset, samples)).data;
  }
  return { header, elevationM, landcover, population };
}
