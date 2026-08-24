// RealEarth map viewer shell: owns the sidebar controls, pack lifecycle, mode
// switching between the flat canvas and the three.js globe, the cursor probe,
// and the settlement tooltip. Pack artifacts are parsed in pack.ts; rendering
// lives in map2d.ts (flat) and globe.ts (sphere).

import { asRecord, asString, errorMessage } from "./coerce.js";
import { DEFAULT_ELEV_SCALE_M, isSafePackPath, loadPack, packMetaFrom } from "./pack.js";
import type { ElevRawCanvas, LoadedPack } from "./pack.js";
import type { CatalogEntry, ElevRawMeta, PackMeta, ProbePoint, Settlement } from "./types.js";
import type { GlobeView } from "./globe.js";
import { Map2D } from "./map2d.js";

const CATALOG_URL = "data/catalog.json";
const DEFAULT_LAYER_ID = "hybrid";
// Exported elevation_raw is single-channel I;16 but canvas often decodes it as
// one 8-bit byte per pixel; the first channel is a coarse height proxy.
const ELEVATION_CHANNEL_MAX = 255;
const PROBE_LON_LAT_DECIMALS = 5;
const PROBE_UV_DECIMALS = 3;
const BBOX_DECIMALS = 2;
const TOOLTIP_COORD_DECIMALS = 3;
const COLOR_PATTERN = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/iu;
const INVALID_COLOR_HEX = "#808080";

type LegendRow = readonly [color: string, label: string];

const HYBRID_LEGEND: ReadonlyArray<LegendRow> = [
  ["#3dd6c6", "Terrain + cover blend"],
  ["#f0a500", "Settlement markers"],
];

const LEGENDS: Record<string, ReadonlyArray<LegendRow>> = {
  elevation: [
    ["#0a285a", "Deep / ocean"],
    ["#2d6b3a", "Lowland"],
    ["#8b6b3a", "Upland"],
    ["#d8d8d8", "High peaks"],
  ],
  landcover: [
    ["#0000ff", "Ocean"],
    ["#004000", "Forest"],
    ["#ffff00", "Desert"],
    ["#ffffff", "Snow/ice"],
    ["#ff0000", "Urban"],
    ["#808080", "Barren"],
  ],
  population: [
    ["#0c0c12", "None"],
    ["#c8a020", "Low"],
    ["#f07020", "Medium"],
    ["#ff2020", "High"],
  ],
  hybrid: HYBRID_LEGEND,
};

function requiredElement<T extends Element>(elementType: new () => T, selector: string): T {
  const element = document.querySelector(selector);
  if (!(element instanceof elementType)) {
    throw new Error(`Viewer markup is missing ${selector}`);
  }
  return element;
}

const els = {
  packSelect: requiredElement(HTMLSelectElement, "#packSelect"),
  jsonFile: requiredElement(HTMLInputElement, "#jsonFile"),
  packInfo: requiredElement(HTMLParagraphElement, "#packInfo"),
  layerSelect: requiredElement(HTMLSelectElement, "#layerSelect"),
  showSettlements: requiredElement(HTMLInputElement, "#showSettlements"),
  showGrid: requiredElement(HTMLInputElement, "#showGrid"),
  opacity: requiredElement(HTMLInputElement, "#opacity"),
  legend: requiredElement(HTMLDivElement, "#legend"),
  btnFlat: requiredElement(HTMLButtonElement, "#btnFlat"),
  btnGlobe: requiredElement(HTMLButtonElement, "#btnGlobe"),
  mapCanvas: requiredElement(HTMLCanvasElement, "#mapCanvas"),
  globeHost: requiredElement(HTMLDivElement, "#globeHost"),
  titleHud: requiredElement(HTMLDivElement, "#titleHud"),
  statusHud: requiredElement(HTMLDivElement, "#statusHud"),
  settlementTip: requiredElement(HTMLDivElement, "#settlementTip"),
  pLon: requiredElement(HTMLElement, "#pLon"),
  pLat: requiredElement(HTMLElement, "#pLat"),
  pElev: requiredElement(HTMLElement, "#pElev"),
  pUv: requiredElement(HTMLElement, "#pUv"),
};

type ViewerMode = "flat" | "globe";

type ViewerState = {
  mode: ViewerMode;
  meta: PackMeta | null;
  settlements: Array<Settlement>;
  layerId: string;
  images: Record<string, HTMLImageElement>;
  elevRaw: ElevRawCanvas | null;
  elevMeta: ElevRawMeta | null;
  map2d: Map2D | null;
  // pending/fulfilled dynamic import of globe.ts (pulls three.js from the
  // CDN); reset on failure so a later Globe click retries.
  globeReady: Promise<GlobeView> | null;
};

const state: ViewerState = {
  mode: "flat",
  meta: null,
  settlements: [],
  layerId: DEFAULT_LAYER_ID,
  images: {},
  elevRaw: null,
  elevMeta: null,
  map2d: null,
  globeReady: null,
};

function setStatus(message: string): void {
  els.statusHud.textContent = message;
}

function readyStatus(): string {
  const layerCount = state.meta === null ? 0 : state.meta.layers.length;
  return `Loaded · ${layerCount} layers`;
}

function renderLegend(layerId: string): void {
  els.legend.replaceChildren();
  const rows = LEGENDS[layerId] ?? HYBRID_LEGEND;
  for (const [color, label] of rows) {
    const row = document.createElement("div");
    row.className = "legend-row";
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = COLOR_PATTERN.test(color) ? color : INVALID_COLOR_HEX;
    row.append(swatch, document.createTextNode(label));
    els.legend.append(row);
  }
}

function fillLayers(meta: PackMeta): void {
  els.layerSelect.replaceChildren();
  for (const layer of meta.layers) {
    const option = document.createElement("option");
    option.value = layer.id;
    option.textContent = layer.label === "" ? layer.id : layer.label;
    els.layerSelect.append(option);
  }
  const first = meta.layers[0];
  if (first !== undefined) {
    state.layerId = first.id;
    els.layerSelect.value = state.layerId;
  }
  renderLegend(state.layerId);
}

function fmt(degrees: number): string {
  return Number.isNaN(degrees) ? "?" : degrees.toFixed(BBOX_DECIMALS);
}

function describePack(meta: PackMeta): void {
  els.titleHud.textContent = meta.name === "" ? "RealEarth" : meta.name;
  const metersText = meta.meters_per_block > 0 ? `~${meta.meters_per_block} m/sample` : "";
  const viewText = meta.view_width > 0 ? ` · view ${meta.view_width}×${meta.view_height}` : "";
  const lines = [
    meta.name === "" ? "pack" : meta.name,
    `bbox ${fmt(meta.bbox.west)}°,${fmt(meta.bbox.south)}° → ${fmt(meta.bbox.east)}°,${fmt(meta.bbox.north)}°`,
    `samples ${meta.sample_width}×${meta.sample_height}${viewText}`,
    metersText,
    `${meta.settlement_count} settlements · ${meta.tiles.length} tiles`,
  ].filter((line) => line !== "");
  els.packInfo.replaceChildren();
  for (const [index, line] of lines.entries()) {
    if (index > 0) {
      els.packInfo.append(document.createElement("br"));
    }
    if (index === 0) {
      const strong = document.createElement("strong");
      strong.textContent = line;
      els.packInfo.append(strong);
      continue;
    }
    els.packInfo.append(document.createTextNode(line));
  }
}

function elevationAt(u: number, v: number): string {
  const elevRaw = state.elevRaw;
  const elevMeta = state.elevMeta;
  if (elevRaw === null || elevMeta === null) {
    return "—";
  }
  const x = Math.min(elevRaw.width - 1, Math.max(0, Math.floor(u * elevRaw.width)));
  const y = Math.min(elevRaw.height - 1, Math.max(0, Math.floor(v * elevRaw.height)));
  const pixel = elevRaw.ctx.getImageData(x, y, 1, 1).data;
  const intensity = (pixel[0] ?? 0) / ELEVATION_CHANNEL_MAX;
  const scaleM = elevMeta.scale_m > 0 ? elevMeta.scale_m : DEFAULT_ELEV_SCALE_M;
  const elev = elevMeta.offset_m + intensity * scaleM;
  return `${elev.toFixed(0)} m (approx)`;
}

function updateProbe(point: ProbePoint | null): void {
  if (point === null) {
    els.pLon.textContent = "—";
    els.pLat.textContent = "—";
    els.pElev.textContent = "—";
    els.pUv.textContent = "—";
    return;
  }
  els.pLon.textContent = `${point.lon.toFixed(PROBE_LON_LAT_DECIMALS)}°`;
  els.pLat.textContent = `${point.lat.toFixed(PROBE_LON_LAT_DECIMALS)}°`;
  els.pUv.textContent = `${point.u.toFixed(PROBE_UV_DECIMALS)}, ${point.v.toFixed(PROBE_UV_DECIMALS)}`;
  els.pElev.textContent = elevationAt(point.u, point.v);
}

function showTip(settlement: Settlement | null, sx: number, sy: number): void {
  if (settlement === null) {
    els.settlementTip.hidden = true;
    return;
  }
  els.settlementTip.hidden = false;
  els.settlementTip.style.left = `${sx}px`;
  els.settlementTip.style.top = `${sy}px`;
  els.settlementTip.replaceChildren();
  const strong = document.createElement("strong");
  strong.textContent = settlement.name;
  els.settlementTip.append(strong);
  els.settlementTip.append(document.createElement("br"));
  els.settlementTip.append(
    document.createTextNode(`${settlement.band} · pop ${settlement.population.toLocaleString()}`)
  );
  els.settlementTip.append(document.createElement("br"));
  els.settlementTip.append(
    document.createTextNode(
      `${settlement.lat.toFixed(TOOLTIP_COORD_DECIMALS)}°, ` +
        `${settlement.lon.toFixed(TOOLTIP_COORD_DECIMALS)}°`
    )
  );
}

function ensureMap2D(): Map2D {
  if (state.map2d === null) {
    const map2d = new Map2D(els.mapCanvas);
    map2d.onProbe = (point) => updateProbe(point);
    map2d.onHoverSettlement = (settlement, sx, sy) => showTip(settlement, sx, sy);
    state.map2d = map2d;
  }
  els.mapCanvas.hidden = false;
  els.globeHost.hidden = true;
  state.map2d.resize();
  return state.map2d;
}

function ensureGlobe(): Promise<GlobeView> {
  els.mapCanvas.hidden = true;
  els.globeHost.hidden = false;
  if (state.globeReady === null) {
    state.globeReady = import("./globe.js").then((globeModule) => {
      const globe = new globeModule.GlobeView(els.globeHost);
      globe.resize();
      return globe;
    });
  }
  return state.globeReady;
}

function setModeButtons(mode: ViewerMode): void {
  els.btnFlat.classList.toggle("active", mode === "flat");
  els.btnGlobe.classList.toggle("active", mode === "globe");
  els.btnFlat.setAttribute("aria-pressed", String(mode === "flat"));
  els.btnGlobe.setAttribute("aria-pressed", String(mode === "globe"));
}

function applyLayer(): void {
  const image = state.images[state.layerId] ?? Object.values(state.images)[0];
  const meta = state.meta;
  if (image === undefined || meta === null) {
    return;
  }
  renderLegend(state.layerId);

  if (state.mode === "flat") {
    const map2d = ensureMap2D();
    map2d.setImage(image, {
      bbox: meta.bbox,
      settlements: state.settlements,
      tileSize: meta.tile_size,
      sampleWidth: meta.sample_width,
      sampleHeight: meta.sample_height,
    });
    map2d.setLayerFlags({
      showSettlements: els.showSettlements.checked,
      showGrid: els.showGrid.checked,
      opacity: Number(els.opacity.value),
    });
    return;
  }
  // Globe mode pulls three.js from the CDN on first use; until it resolves
  // the HUD says so, and a failed import reports and falls back to the flat
  // map instead of leaving a dead globe host.
  setStatus("Loading globe…");
  ensureGlobe()
    .then((globe) => {
      if (state.mode !== "globe") {
        return;
      }
      // re-measure in case the stage resized while flat mode was showing
      globe.resize();
      globe.setTexture(
        image,
        els.showSettlements.checked ? state.settlements : [],
        meta.bbox
      );
      setStatus(readyStatus());
    })
    .catch((error: unknown) => {
      // drop the failed import so the next Globe click retries the fetch
      state.globeReady = null;
      state.mode = "flat";
      setModeButtons("flat");
      setStatus(errorMessage(error));
      applyLayer();
    });
}

function setMode(mode: ViewerMode): void {
  state.mode = mode;
  setModeButtons(mode);
  applyLayer();
}

function adoptPack(pack: LoadedPack): void {
  state.meta = pack.meta;
  state.images = pack.images;
  state.settlements = pack.settlements;
  state.elevRaw = pack.elevRaw;
  state.elevMeta = pack.meta.elev_raw;
  fillLayers(pack.meta);
  describePack(pack.meta);
  applyLayer();
  setStatus(readyStatus());
}

function catalogEntriesFrom(candidate: unknown): Array<CatalogEntry> {
  if (!Array.isArray(candidate)) {
    return [];
  }
  const entries: Array<CatalogEntry> = [];
  for (const item of candidate) {
    const record = asRecord(item);
    const path = asString(record.path);
    if (path !== "" && isSafePackPath(path)) {
      entries.push({ path, name: asString(record.name) });
    }
  }
  return entries;
}

function renderBrokenPackNotice(pack: string): void {
  els.packInfo.replaceChildren();
  els.packInfo.append(document.createTextNode(`Missing or broken ${pack}/viewer.json.`));
  els.packInfo.append(document.createElement("br"));
  const exportHint = document.createElement("code");
  exportHint.textContent =
    "realearth export-viewer --pack data/samples/demo_region --out viewer/data/demo";
  els.packInfo.append(document.createTextNode("From repo: "), exportHint);
  els.packInfo.append(document.createElement("br"));
  const serveHint = document.createElement("code");
  serveHint.textContent = "realearth serve";
  els.packInfo.append(document.createTextNode("then "), serveHint);
}

async function boot(): Promise<void> {
  const params = new URLSearchParams(location.search);
  // A crafted ?pack= link must not point the viewer at other origins or
  // outside the served tree; unsafe values fall back to the bundled pack.
  const requested = params.get("pack");
  const pack = requested !== null && isSafePackPath(requested) ? requested : els.packSelect.value;
  const [catalog] = await Promise.all([
    // absent or broken catalog is normal for minimal exports
    fetch(CATALOG_URL).catch(() => null),
    loadPack(pack)
      .then(adoptPack)
      .catch((error: unknown) => {
        setStatus(`Cannot load ${pack}: ${errorMessage(error)}`);
        renderBrokenPackNotice(pack);
      }),
  ]);
  if (catalog !== null && catalog.ok) {
    for (const entry of catalogEntriesFrom(await catalog.json())) {
      const option = document.createElement("option");
      option.value = entry.path;
      option.textContent = entry.name === "" ? entry.path : entry.name;
      els.packSelect.append(option);
    }
  }
  els.packSelect.value = pack;
}

// events
els.btnFlat.addEventListener("click", () => setMode("flat"));
els.btnGlobe.addEventListener("click", () => setMode("globe"));
els.layerSelect.addEventListener("change", () => {
  state.layerId = els.layerSelect.value;
  applyLayer();
});
els.showSettlements.addEventListener("change", () => applyLayer());
els.showGrid.addEventListener("change", () => {
  if (state.map2d !== null) {
    state.map2d.setLayerFlags({ showGrid: els.showGrid.checked });
  }
});
els.opacity.addEventListener("input", () => {
  if (state.map2d !== null) {
    state.map2d.setLayerFlags({ opacity: Number(els.opacity.value) });
  }
});
els.packSelect.addEventListener("change", () => {
  loadPack(els.packSelect.value)
    .then(adoptPack)
    .catch((error: unknown) => {
      setStatus(errorMessage(error));
      els.packInfo.textContent = errorMessage(error);
    });
});

els.jsonFile.addEventListener("change", () => {
  const file = els.jsonFile.files?.[0];
  if (file === undefined) {
    return;
  }
  // The file picker only gives viewer.json; sibling images need a served
  // folder. Meta-only preview tells the user how to get the full pack.
  file
    .text()
    .then((text) => JSON.parse(text))
    .then((meta) => {
      state.meta = packMetaFrom(meta);
      fillLayers(state.meta);
      setStatus("Use a served pack path for full layers. Meta only loaded for preview.");
      els.packInfo.textContent =
        "Loaded viewer.json from disk. Serve the export folder over HTTP and pick it in Dataset for images.";
    })
    .catch((error: unknown) => {
      setStatus(errorMessage(error));
    });
});

await boot();
