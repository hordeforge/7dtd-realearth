// Coercion helpers for untrusted JSON payloads: viewer pack metadata
// (pack.ts) and the dashboard API envelope (overview.ts). Each helper returns
// a concrete default instead of undefined so downstream code stays total; the
// shape guards live here rather than across every reader.

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function asString(candidate: unknown): string {
  return typeof candidate === "string" ? candidate : "";
}

export function asNumber(candidate: unknown): number {
  return typeof candidate === "number" && Number.isFinite(candidate) ? candidate : 0;
}

export function asNumberOr(candidate: unknown, fallback: number): number {
  return typeof candidate === "number" && Number.isFinite(candidate) ? candidate : fallback;
}

export function asRecord(candidate: unknown): Record<string, unknown> {
  if (typeof candidate !== "object" || candidate === null) {
    return {};
  }
  const record: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(candidate)) {
    record[key] = entry;
  }
  return record;
}
