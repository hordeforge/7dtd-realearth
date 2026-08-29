// RealEarth map viewer shell: owns the sidebar controls, pack lifecycle, mode
// switching between the flat canvas and the three.js globe, the cursor probe,
// and the settlement tooltip. Pack artifacts are parsed in pack.ts; rendering
// lives in map2d.ts (flat) and globe.ts (sphere).

import { asRecord, asString, errorMessage } from "./coerce.js";
import { DEFAULT_ELEV_SCALE_M, isSafePackPath, loadPack, packMetaFrom } from "./pack.js";
import type { ElevRawCanvas, LoadedPack } from "./pack.js";
import type {
  CatalogEntry,
  ElevRawMeta,
  LonLatPoint,
  PackMeta,
  PlayerFix,
  ProbePoint,
  Settlement,
} from "./types.js";
import type { GlobeView } from "./globe.js";
import { Map2D } from "./map2d.js";

const CATALOG_URL = "data/catalog.json";
const PLAYER_URL = "data/player.json";
const PLAYER_POLL_MS = 5000;
const ZOOM_BUTTON_STEP = 1.25;
const ZOOM_BUTTON_STEP_OUT = 1 / ZOOM_BUTTON_STEP;
const LON_LIMIT_DEGREES = 180;
const LAT_LIMIT_DEGREES = 90;
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
  btnJumpPlayer: requiredElement(HTMLButtonElement, "#btnJumpPlayer"),
  btnSpinToggle: requiredElement(HTMLButtonElement, "#btnSpinToggle"),
  jumpLat: requiredElement(HTMLInputElement, "#jumpLat"),
  jumpLon: requiredElement(HTMLInputElement, "#jumpLon"),
  btnJumpCoords: requiredElement(HTMLButtonElement, "#btnJumpCoords"),
  btnZoomIn: requiredElement(HTMLButtonElement, "#btnZoomIn"),
  btnZoomOut: requiredElement(HTMLButtonElement, "#btnZoomOut"),
  playerHud: requiredElement(HTMLDivElement, "#playerHud"),
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
  // live instance once the dynamic globe import resolved; null otherwise
  globeInstance: GlobeView | null;
  // pending/fulfilled dynamic import of globe.ts (pulls three.js from the
  // CDN); reset on failure so a later Globe click retries.
  globeReady: Promise<GlobeView> | null;
  // latest fix from the optional data/player.json feed; null when absent
  player: PlayerFix | null;
  // set when a pack loads so the globe flies to frame its region once
  globeNeedsFrame: boolean;
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
  globeInstance: null,
  globeReady: null,
  player: null,
  globeNeedsFrame: true,
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
  const seaText = meta.sea_level_game_y > 0 ? ` · sea Y ${meta.sea_level_game_y}` : "";
  const lines = [
    meta.name === "" ? "pack" : meta.name,
    `bbox ${fmt(meta.bbox.west)}°,${fmt(meta.bbox.south)}° → ${fmt(meta.bbox.east)}°,${fmt(meta.bbox.north)}°`,
    `samples ${meta.sample_width}×${meta.sample_height}${viewText}`,
    `${metersText}${seaText}`,
    `${meta.settlement_count} settlements · ${meta.tiles.length} tiles`,
  ].filter((line) => line !== "");
  // Data provenance: export-time sources plus any free-form notes, rendered
  // after the geometry block. Packs without either omit the section (most
  // minimal exports carry at least the sources list).
  const sources = meta.sources.filter((source) => source !== "");
  const provenance: Array<string> = [];
  if (sources.length > 0) {
    provenance.push(`sources: ${sources.join(" · ")}`);
  }
  if (meta.notes !== "") {
    provenance.push(meta.notes);
  }
  els.packInfo.replaceChildren();
  for (const [index, line] of lines.concat(provenance).entries()) {
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

function showTip(settlement: Settlement | null, sx: number, sy: number): void {  if (settlement === null) {
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

function coordinateFromText(raw: string, min: number, max: number): number | null {
  const text = raw.trim();
  if (text === "") {
    return null;
  }
  const value = Number(text);
  if (!Number.isFinite(value)) {
    return null;
  }
  return value >= min && value <= max ? value : null;
}

// Keep the assistive-tech state in step with the visual .invalid border:
// screen readers must hear that the field failed validation (WCAG 3.3.1).
function setCoordinateInvalid(input: HTMLInputElement, invalid: boolean): void {
  input.classList.toggle("invalid", invalid);
  input.setAttribute("aria-invalid", invalid ? "true" : "false");
}

function finiteNumberIn(candidate: unknown, min: number, max: number): number | null {
  if (typeof candidate !== "number" || !Number.isFinite(candidate)) {
    return null;
  }
  return candidate >= min && candidate <= max ? candidate : null;
}

// Boundary parse of one data/player.json fix; anything malformed or out of
// range means "no known player position".
function playerFrom(candidate: unknown): PlayerFix | null {
  const record = asRecord(candidate);
  const lon = finiteNumberIn(record.lon, -LON_LIMIT_DEGREES, LON_LIMIT_DEGREES);
  const lat = finiteNumberIn(record.lat, -LAT_LIMIT_DEGREES, LAT_LIMIT_DEGREES);
  if (lon === null || lat === null) {
    return null;
  }
  const name = asString(record.name);
  return { name: name === "" ? "Player" : name, lon, lat };
}

// Deep link format: ?player=lat,lon (Google-Maps-style order).
function playerParamFrom(raw: string | null): LonLatPoint | null {
  if (raw === null) {
    return null;
  }
  const [latText, lonText] = raw.split(",");
  if (latText === undefined || lonText === undefined) {
    return null;
  }
  const lat = coordinateFromText(latText, -LAT_LIMIT_DEGREES, LAT_LIMIT_DEGREES);
  const lon = coordinateFromText(lonText, -LON_LIMIT_DEGREES, LON_LIMIT_DEGREES);
  return lat === null || lon === null ? null : { lon, lat };
}

function spinEnabledFromButton(): boolean {
  return els.btnSpinToggle.getAttribute("aria-pressed") === "true";
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
      // Publish before any fallible setup: a throw below must leave the
      // instance reachable so failure handlers can dispose it instead of
      // orphaning its render loop and resize listener.
      state.globeInstance = globe;
      globe.resize();
      globe.setSpin(spinEnabledFromButton());
      globe.setPlayerMarker(state.player);
      return globe;
    });
  }
  return state.globeReady;
}

function renderFlat(image: HTMLImageElement, meta: PackMeta): void {
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
}

function setModeButtons(mode: ViewerMode): void {
  els.btnFlat.classList.toggle("active", mode === "flat");
  els.btnGlobe.classList.toggle("active", mode === "globe");
  els.btnFlat.setAttribute("aria-pressed", String(mode === "flat"));
  els.btnGlobe.setAttribute("aria-pressed", String(mode === "globe"));
  els.btnSpinToggle.disabled = mode !== "globe";
}

function applyLayer(): void {
  const image = state.images[state.layerId] ?? Object.values(state.images)[0];
  const meta = state.meta;
  if (image === undefined || meta === null) {
    return;
  }
  renderLegend(state.layerId);

  if (state.mode === "flat") {
    renderFlat(image, meta);
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
      globe.setPlayerMarker(state.player);
      if (state.globeNeedsFrame) {
        state.globeNeedsFrame = false;
        globe.frameRegion(meta.bbox);
      }
      setStatus(readyStatus());
    })
    .catch((error: unknown) => {
      // drop the failed import so the next Globe click retries the fetch
      state.globeReady = null;
      // A constructed view must be torn down or its requestAnimationFrame
      // loop, resize listener, and WebGL context outlive this attempt (and
      // multiply with every retry).
      state.globeInstance?.dispose();
      state.globeInstance = null;
      state.mode = "flat";
      setModeButtons("flat");
      setStatus(errorMessage(error));
      renderFlat(image, meta);
    });
}

function setMode(mode: ViewerMode): void {
  // Hiding the focused canvas would drop focus to <body>; carry keyboard
  // focus across to the view that is becoming visible instead.
  const active = document.activeElement;
  const stageHadFocus =
    active === els.mapCanvas || (active instanceof Node && els.globeHost.contains(active));
  state.mode = mode;
  setModeButtons(mode);
  applyLayer();
  if (!stageHadFocus) {
    return;
  }
  if (mode === "flat") {
    els.mapCanvas.focus();
  } else {
    els.globeHost.focus();
  }
}

// Fly the globe camera to a lon/lat (Google-Earth-style hop).
function flyGlobeTo(position: LonLatPoint): void {
  ensureGlobe()
    .then((globe) => {
      if (state.mode !== "globe") {
        return;
      }
      globe.resize();
      globe.flyTo(position);
    })
    .catch((error: unknown) => {
      state.globeReady = null;
      // Same teardown contract as applyLayer: never orphan a live view.
      state.globeInstance?.dispose();
      state.globeInstance = null;
      setStatus(errorMessage(error));
      setMode("flat");
    });
}

function goTo(position: LonLatPoint): void {
  if (state.mode === "globe") {
    flyGlobeTo(position);
    return;
  }
  ensureMap2D().centerOn(position);
  setStatus(`Centered on ${position.lat.toFixed(TOOLTIP_COORD_DECIMALS)}, ${position.lon.toFixed(TOOLTIP_COORD_DECIMALS)}`);
}

function zoomActiveView(factor: number): void {
  if (state.mode === "flat") {
    const map2d = state.map2d;
    const parent = els.mapCanvas.parentElement;
    if (map2d === null || parent === null) {
      return;
    }
    map2d.zoomAt(parent.clientWidth / 2, parent.clientHeight / 2, factor);
    map2d.draw();
    return;
  }
  state.globeInstance?.zoomBy(factor);
}

function setSpinToggle(enabled: boolean): void {
  els.btnSpinToggle.setAttribute("aria-pressed", String(enabled));
  els.btnSpinToggle.classList.toggle("active", enabled);
  els.btnSpinToggle.textContent = enabled ? "Spinning" : "Paused";
  state.globeInstance?.setSpin(enabled);
}

function toggleSpin(): void {
  setSpinToggle(!spinEnabledFromButton());
}

// Publish a player fix (or its absence) to the sidebar, HUD, and both views.
function applyPlayer(player: PlayerFix | null): void {
  state.player = player;
  els.btnJumpPlayer.disabled = player === null;
  if (player === null) {
    els.btnJumpPlayer.setAttribute("title", "No player position known");
  } else {
    els.btnJumpPlayer.removeAttribute("title");
  }
  els.playerHud.hidden = player === null;
  if (player !== null) {
    els.playerHud.textContent =
      `${player.name} · ${player.lat.toFixed(TOOLTIP_COORD_DECIMALS)}°, ` +
      `${player.lon.toFixed(TOOLTIP_COORD_DECIMALS)}°`;
  }
  state.map2d?.setPlayer(player);
  state.globeInstance?.setPlayerMarker(player);
}

function refreshPlayer(): void {
  // The feed is optional; absence or a stale response between polls is
  // normal for offline packs.
  fetch(PLAYER_URL, { cache: "no-store" })
    .then(async (response) => applyPlayer(response.ok ? playerFrom(await response.json()) : null))
    .catch(() => applyPlayer(null));
}

function adoptPack(pack: LoadedPack): void {
  state.meta = pack.meta;
  state.images = pack.images;
  state.settlements = pack.settlements;
  state.elevRaw = pack.elevRaw;
  state.elevMeta = pack.meta.elev_raw;
  state.globeNeedsFrame = true;
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
  // ?player=lat,lon seeds the jump inputs and flies there after the pack
  // settles, whichever view ends up active.
  const linkedPlayer = playerParamFrom(params.get("player"));
  if (linkedPlayer !== null) {
    els.jumpLat.value = String(linkedPlayer.lat);
    els.jumpLon.value = String(linkedPlayer.lon);
    goTo(linkedPlayer);
  }
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
  setStatus("Loading pack…");
  loadPack(els.packSelect.value)
    .then(adoptPack)
    .catch((error: unknown) => {
      setStatus(errorMessage(error));
      els.packInfo.textContent = errorMessage(error);
    });
});

els.btnJumpPlayer.addEventListener("click", () => {
  if (state.player !== null) {
    goTo(state.player);
  }
});
els.btnJumpCoords.addEventListener("click", () => {
  const lat = coordinateFromText(els.jumpLat.value, -LAT_LIMIT_DEGREES, LAT_LIMIT_DEGREES);
  const lon = coordinateFromText(els.jumpLon.value, -LON_LIMIT_DEGREES, LON_LIMIT_DEGREES);
  setCoordinateInvalid(els.jumpLat, lat === null);
  setCoordinateInvalid(els.jumpLon, lon === null);
  if (lat === null || lon === null) {
    setStatus("Jump needs lat in [-90, 90] and lon in [-180, 180]");
    return;
  }
  goTo({ lon, lat });
});
for (const input of [els.jumpLat, els.jumpLon]) {
  input.addEventListener("input", () => setCoordinateInvalid(input, false));
  input.addEventListener("keydown", (event: KeyboardEvent) => {
    if (event.key === "Enter") {
      event.preventDefault();
      els.btnJumpCoords.click();
    }
  });
}
els.btnSpinToggle.addEventListener("click", () => toggleSpin());
els.btnZoomIn.addEventListener("click", () => zoomActiveView(ZOOM_BUTTON_STEP));
els.btnZoomOut.addEventListener("click", () => zoomActiveView(ZOOM_BUTTON_STEP_OUT));

// "p" anywhere outside a form field jumps to the latest player fix.
globalThis.addEventListener("keydown", (event: KeyboardEvent) => {
  const target = event.target;
  const typing =
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement;
  if (typing || event.ctrlKey || event.metaKey || event.altKey) {
    return;
  }
  if (event.key.toLowerCase() === "p" && state.player !== null) {
    goTo(state.player);
  }
});

// optional live position feed; polled so an external writer (game mod,
// script) can move the marker without reloading
// The globe never auto-spins under prefers-reduced-motion; keep the toggle's
// pressed state honest about that instead of advertising a spin that cannot
// happen.
if (globalThis.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  setSpinToggle(false);
}
refreshPlayer();
setInterval(refreshPlayer, PLAYER_POLL_MS);

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
