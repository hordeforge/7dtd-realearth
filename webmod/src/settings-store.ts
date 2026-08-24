// Default pack preference persisted in localStorage so an admin picks the
// dataset once. When storage is unavailable (private mode, disabled storage)
// the choice still applies for the current session.

import { DEFAULT_PACK_PATH } from "./base";

const STORAGE_KEY = "realearth.defaultPack";

let storageAvailable = true;
let rememberedPath: string | null = null;

function readRaw(key: string): string | null {
  try {
    return globalThis.localStorage.getItem(key);
    // oxlint-disable-next-line @rikalabs/no-silent-catch-fallback -- deliberate: storage can be blocked (private mode / disabled storage); the flag makes the session-only fallback explicit
  } catch {
    storageAvailable = false;
    return null;
  }
}

export function getDefaultPackPath(): string {
  if (rememberedPath !== null) {
    return rememberedPath;
  }
  const raw = readRaw(STORAGE_KEY);
  const next = raw === null || raw === "" ? DEFAULT_PACK_PATH : raw;
  rememberedPath = next;
  return next;
}

// Outcome of a save, so the UI can tell "kept forever" from "kept only for
// this session"; reporting a session-only choice as plain Saved would lie.
export type DefaultPackSave = "rejected" | "persisted" | "session-only";

export function setDefaultPackPath(path: string): DefaultPackSave {
  const trimmed = path.trim();
  if (trimmed === "") {
    return "rejected";
  }
  rememberedPath = trimmed;
  if (!storageAvailable) {
    return "session-only";
  }
  try {
    globalThis.localStorage.setItem(STORAGE_KEY, trimmed);
    return "persisted";
    // oxlint-disable-next-line @rikalabs/no-silent-catch-fallback -- deliberate: writes can fail when storage is full or blocked; the session keeps the in-memory value
  } catch {
    storageAvailable = false;
    return "session-only";
  }
}
