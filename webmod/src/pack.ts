// Pack loading for the RealEarth webui. A pack is the output of `realearth
// export-viewer`: viewer.json metadata plus one PNG per layer, an optional
// settlements.json, and an optional raw elevation PNG for the cursor probe.
// Missing optional artifacts degrade gracefully; a missing viewer.json is a
// hard error because there is nothing to render.

import { asNumber, asNumberOr, asRecord, asString, errorMessage } from "./coerce";
import type { Bbox, ElevRawMeta, LayerInfo, PackMeta, Settlement } from "./types";

const DEFAULT_ELEV_SCALE_M = 4500;

// Pack paths are joined onto MOD_BASE_URL for every fetch. A path from the
// ?pack= query param (or the pack input) must stay inside the mod's served
// tree: no absolute paths, no scheme, no backslashes, no dot-dot traversal.
export function isSafePackPath(path: string): boolean {
  return (
    path !== "" &&
    !path.startsWith("/") &&
    !path.includes("\\") &&
    !/^[a-z][a-z0-9+.-]*:/iu.test(path) &&
    !path.split("/").includes("..")
  );
}

export type LoadedLayer = {
  id: string;
  image: HTMLImageElement;
};

export type ElevRawCanvas = {
  ctx: CanvasRenderingContext2D;
  width: number;
  height: number;
};

export type LoadedPack = {
  meta: PackMeta;
  layers: Array<LoadedLayer>;
  settlements: Array<Settlement>;
  elevRaw: ElevRawCanvas | null;
  elevMeta: ElevRawMeta | null;
  warnings: Array<string>;
  path: string;
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

function packMetaFrom(candidate: unknown): PackMeta {
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
    throw new Error(`Cannot load ${url} (HTTP ${response.status})`);
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

async function loadLayers(baseUrl: string, layers: Array<LayerInfo>): Promise<Array<LoadedLayer>> {
  const loaded: Array<LoadedLayer> = [];
  for (const layer of layers) {
    const image = await loadImage(`${baseUrl}${layer.file}`);
    loaded.push({ id: layer.id, image });
  }
  return loaded;
}

async function loadSettlements(url: string): Promise<Array<Settlement>> {
  const response = await fetch(url);
  if (!response.ok) {
    return [];
  }
  return settlementListFrom(await response.json());
}

async function loadElevRaw(
  baseUrl: string,
  meta: ElevRawMeta | null,
  warnings: Array<string>
): Promise<ElevRawCanvas | null> {
  if (meta === null) {
    return null;
  }
  const image = await loadImage(`${baseUrl}${meta.file}`).catch((error: unknown) => {
    warnings.push(errorMessage(error));
    return null;
  });
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

export async function loadPack(baseUrl: string, path: string): Promise<LoadedPack> {
  if (!isSafePackPath(path)) {
    throw new Error(`Refusing unsafe pack path: ${path}`);
  }
  const base = `${baseUrl}${path}/`;
  const meta = packMetaFrom(await fetchJson(`${base}viewer.json`));
  if (meta.layers.length === 0) {
    throw new Error(`Pack ${path} has no layers`);
  }
  const layers = await loadLayers(base, meta.layers);
  const settlements = await loadSettlements(`${base}settlements.json`);
  const warnings: Array<string> = [];
  const elevRaw = await loadElevRaw(base, meta.elev_raw, warnings);
  return { meta, layers, settlements, elevRaw, elevMeta: meta.elev_raw, warnings, path };
}
