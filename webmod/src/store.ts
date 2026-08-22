// In-memory store for the currently loaded pack. The Map and Overview pages
// share one loaded pack: Map loads it, Overview reads it, and both re-render
// on change through packStore.subscribe.

import { DEFAULT_PACK_PATH } from "./base";
import type { LoadedPack } from "./pack";

type Listener = () => void;

let activePack: LoadedPack | null = null;
let activePath = DEFAULT_PACK_PATH;
const listeners = new Set<Listener>();

export const packStore = {
  get(): LoadedPack | null {
    return activePack;
  },
  path(): string {
    return activePath;
  },
  set(next: LoadedPack, path: string): void {
    activePack = next;
    activePath = path;
    for (const listener of listeners) {
      listener();
    }
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};
