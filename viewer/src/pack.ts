// Pack loading for the standalone viewer. A pack is the output of
// `realearth export-viewer`: viewer.json metadata plus one PNG per layer, an
// optional settlements.json, and an optional raw elevation PNG for the cursor
// probe. Missing optional artifacts degrade gracefully; a missing or
// layer-less viewer.json is a hard error because there is nothing to render.
// All artifacts are fetched in parallel (viewer packs can be large).

import { asNumber, asNumberOr, asRecord, asString } from "./coerce.js";
import type { Bbox, ElevRawMeta, LayerInfo, PackMeta, Settlement } from "./types.js";

export const DEFAULT_ELEV_SCALE_M = 4500;

// Pack paths are joined into fetch URLs (the ?pack= query param, catalog
// entries, the dataset dropdown). A path must stay inside the served export
// tree: no absolute paths, no scheme (cross-origin pack injection), no
// backslashes, no dot-dot traversal. Checks run against the decoded form so
// %2e%2e cannot smuggle a traversal segment past a literal ".." test; a
// malformed escape fails closed. Same guard as ../webmod/src/pack.ts.
export function isSafePackPath(path: string): boolean {
  let decoded: string;
  try {
    decoded = decodeURIComponent(path);
    // oxlint-disable-next-line @rikalabs/no-silent-catch-fallback -- deliberate: a malformed escape is unparseable input, so validation fails closed
  } catch {
    return false;
  }
  return (
    decoded !== "" &&
    !decoded.startsWith("/") &&
    !decoded.includes("\\") &&
    !/^[a-z][a-z0-9+.-]*:/iu.test(decoded) &&
    !decoded.split("/").includes("..")
  );
}

export type ElevRawCanvas = {
  ctx: CanvasRenderingContext2D;
  width: number;
  height: number;
};

export type LoadedPack = {
  meta: PackMeta;
  images: Record<string, HTMLImageElement>;
  settlements: Array<Settlement>;
  elevRaw: ElevRawCanvas | null;
};

function bboxFrom(candidate: unknown): Bbox {
  const record = asRecord(candidate);
  return {
    west: asNumber(record.west),
    south: asNumber(record.south),
    east: asNumber(record.east),
    north: asNumber(record.north),
  };
}

function elevRawFrom(candidate: unknown): ElevRawMeta | null {
  const record = asRecord(candidate);
  const file = asString(record.file);
  if (file === "") {
    return null;
  }
  return {
    file,
    offset_m: asNumber(record.offset_m),
    scale_m: asNumberOr(record.scale_m, DEFAULT_ELEV_SCALE_M),
  };
}

function stringListFrom(candidate: unknown): Array<string> {
  if (!Array.isArray(candidate)) {
    return [];
  }
  const strings: Array<string> = [];
  for (const entry of candidate) {
    const text = asString(entry);
    if (text !== "") {
      strings.push(text);
    }
  }
  return strings;
}

function layerListFrom(candidate: unknown): Array<LayerInfo> {
  if (!Array.isArray(candidate)) {
    return [];
  }
  const layers: Array<LayerInfo> = [];
  for (const entry of candidate) {
    const record = asRecord(entry);
    const id = asString(record.id);
    if (id !== "") {
      layers.push({ id, file: asString(record.file), label: asString(record.label) });
    }
  }
  return layers;
}

function settlementListFrom(candidate: unknown): Array<Settlement> {
  if (!Array.isArray(candidate)) {
    return [];
  }
  const settlements: Array<Settlement> = [];
  for (const entry of candidate) {
    const record = asRecord(entry);
    const name = asString(record.name);
    if (name === "") {
      continue;
    }
    settlements.push({
      name,
      lon: asNumber(record.lon),
      lat: asNumber(record.lat),
      population: asNumber(record.population),
      band: asString(record.band),
      edge_radius_m: asNumber(record.edge_radius_m),
      edge_source: asString(record.edge_source),
    });
  }
  return settlements;
}

export function packMetaFrom(candidate: unknown): PackMeta {
  const record = asRecord(candidate);
  return {
    name: asString(record.name),
    version: asNumber(record.version),
    bbox: bboxFrom(record.bbox),
    sample_width: asNumber(record.sample_width),
    sample_height: asNumber(record.sample_height),
    view_width: asNumber(record.view_width),
    view_height: asNumber(record.view_height),
    scale: asNumber(record.scale),
    tile_size: asNumber(record.tile_size),
    meters_per_block: asNumber(record.meters_per_block),
    world_width: asNumber(record.world_width),
    world_height: asNumber(record.world_height),
    sea_level_game_y: asNumber(record.sea_level_game_y),
    tiles: Array.isArray(record.tiles) ? record.tiles : [],
    sources: stringListFrom(record.sources),
    notes: asString(record.notes),
    layers: layerListFrom(record.layers),
    settlement_count: asNumber(record.settlement_count),
    elev_raw: elevRawFrom(record.elev_raw),
  };
}

async function fetchJson(url: string): Promise<unknown> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Cannot load ${url} (${response.status})`);
  }
  return response.json();
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.addEventListener("load", () => resolve(image));
    image.addEventListener("error", () => reject(new Error(`Failed to load ${url}`)));
    image.src = url;
  });
}

async function loadLayerImages(
  base: string,
  layers: ReadonlyArray<LayerInfo>
): Promise<Record<string, HTMLImageElement>> {
  const loaded = await Promise.all(
    layers.map(async (layer) => ({ id: layer.id, image: await loadImage(`${base}/${layer.file}`) }))
  );
  const images: Record<string, HTMLImageElement> = {};
  for (const pair of loaded) {
    images[pair.id] = pair.image;
  }
  return images;
}

async function loadSettlements(url: string): Promise<Array<Settlement>> {
  // Optional artifact: transport failure or an unparsable body degrades to
  // "no settlements" exactly like a non-2xx status, instead of failing the
  // whole pack whose layers already loaded. Same as ../webmod/src/pack.ts.
  const response = await fetch(url).catch(() => null);
  if (response === null || !response.ok) {
    return [];
  }
  return response.json().then(settlementListFrom).catch(() => []);
}

async function loadElevRaw(base: string, elevMeta: ElevRawMeta | null): Promise<ElevRawCanvas | null> {
  // Missing or undecodable raw elevation degrades the cursor probe to
  // "no data"; it never fails the pack.
  if (elevMeta === null) {
    return null;
  }
  const image = await loadImage(`${base}/${elevMeta.file}`).catch(() => null);
  if (image === null) {
    return null;
  }
  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (ctx === null) {
    return null;
  }
  ctx.drawImage(image, 0, 0);
  return { ctx, width: canvas.width, height: canvas.height };
}

export async function loadPack(baseUrl: string): Promise<LoadedPack> {
  if (!isSafePackPath(baseUrl)) {
    throw new Error(`Refusing unsafe pack path: ${baseUrl}`);
  }
  const base = baseUrl.replace(/\/$/u, "");
  const meta = packMetaFrom(await fetchJson(`${base}/viewer.json`));
  if (meta.layers.length === 0) {
    throw new Error(`Pack ${base} has no layers`);
  }
  const [settlements, images, elevRaw] = await Promise.all([
    loadSettlements(`${base}/settlements.json`),
    loadLayerImages(base, meta.layers),
    loadElevRaw(base, meta.elev_raw),
  ]);
  return { meta, images, settlements, elevRaw };
}
