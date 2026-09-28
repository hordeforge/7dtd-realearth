// Read a byte stream whole, refusing to buffer more than `cap` bytes. The
// check runs while the stream is read, so a source that keeps producing past
// the cap is cancelled at the first chunk over rather than buffered first.
// Both capped reads in the viewer go through here: a fetched .rte body
// (app.ts) and an inflated tile section (rte.ts).

export async function readCapped(
  stream: ReadableStream<Uint8Array>,
  cap: number,
  subject: string
): Promise<Uint8Array> {
  const reader = stream.getReader();
  const chunks: Array<Uint8Array> = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    if (value === undefined) {
      continue;
    }
    total += value.byteLength;
    if (total > cap) {
      await reader.cancel();
      throw new Error(`${subject} exceeds the ${cap} byte cap`);
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let at = 0;
  for (const chunk of chunks) {
    out.set(chunk, at);
    at += chunk.byteLength;
  }
  return out;
}
