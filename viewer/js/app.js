import { Map2D } from "./map2d.js";

const LEGENDS = {
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
  hybrid: [
    ["#3dd6c6", "Terrain + cover blend"],
    ["#f0a500", "Settlement markers"],
  ],
};

// Snapshot shape guards: the export packs may omit optional sections. Coerce
// once here instead of fallback-defaulting every property access in the view.
function objOrEmpty(candidate) {
  return candidate !== undefined && candidate !== null && typeof candidate === "object" ? candidate : {};
}
function listOrEmpty(candidate) {
  return Array.isArray(candidate) ? candidate : [];
}
function strOrEmpty(candidate) {
  return candidate === undefined || candidate === null ? "" : candidate;
}
function numOrZero(candidate) {
  return typeof candidate === "number" && Number.isFinite(candidate) ? candidate : 0;
}
function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}
function esc(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const els = {
  packSelect: document.querySelector("#packSelect"),
  jsonFile: document.querySelector("#jsonFile"),
  packInfo: document.querySelector("#packInfo"),
  layerSelect: document.querySelector("#layerSelect"),
  showSettlements: document.querySelector("#showSettlements"),
  showGrid: document.querySelector("#showGrid"),
  opacity: document.querySelector("#opacity"),
  legend: document.querySelector("#legend"),
  btnFlat: document.querySelector("#btnFlat"),
  btnGlobe: document.querySelector("#btnGlobe"),
  mapCanvas: document.querySelector("#mapCanvas"),
  globeHost: document.querySelector("#globeHost"),
  titleHud: document.querySelector("#titleHud"),
  statusHud: document.querySelector("#statusHud"),
  settlementTip: document.querySelector("#settlementTip"),
  pLon: document.querySelector("#pLon"),
  pLat: document.querySelector("#pLat"),
  pElev: document.querySelector("#pElev"),
  pUv: document.querySelector("#pUv"),
};

const state = {
  mode: "flat",
  baseUrl: "",
  meta: null,
  settlements: [],
  layerId: "hybrid",
  images: {},
  elevRaw: null,
  elevMeta: null,
  map2d: null,
  // pending/fulfilled dynamic import of globe.js (pulls three.js from the CDN);
  // reset on failure so a later Globe click retries.
  globeReady: null,
};

function setStatus(msg) {
  els.statusHud.textContent = msg;
}

function readyStatus() {
  return `Loaded · ${listOrEmpty(state.meta.layers).length} layers`;
}

function renderLegend(layerId) {
  const rows = LEGENDS[layerId] || LEGENDS.hybrid;
  els.legend.innerHTML = rows
    .map(
      ([color, label]) =>
        `<div class="legend-row"><span class="swatch" style="background:${color}"></span>${label}</div>`
    )
    .join("");
}

function fillLayers(meta) {
  els.layerSelect.innerHTML = "";
  const layers = listOrEmpty(meta.layers);
  for (const layer of layers) {
    const opt = document.createElement("option");
    opt.value = layer.id;
    opt.textContent = layer.label || layer.id;
    els.layerSelect.append(opt);
  }
  if (layers.length > 0) {
    state.layerId = layers[0].id;
    els.layerSelect.value = state.layerId;
  }
  renderLegend(state.layerId);
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.addEventListener("load", () => resolve(img));
    img.addEventListener("error", () => reject(new Error(`failed to load ${url}`)));
    img.src = url;
  });
}

// Optional sibling artifact; absence is not a failure.
async function fetchSettlements(baseUrl) {
  const res = await fetch(`${baseUrl}/settlements.json`).catch(() => null);
  return res && res.ok ? res.json() : [];
}

async function fetchElevationRaw(baseUrl, elevMeta) {
  if (!elevMeta || !elevMeta.file) {
    return null;
  }
  const img = await loadImage(`${baseUrl}/${elevMeta.file}`).catch(() => null);
  if (!img) {
    return null;
  }
  const c = document.createElement("canvas");
  c.width = img.naturalWidth;
  c.height = img.naturalHeight;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0);
  return { ctx, w: c.width, h: c.height };
}

async function fetchLayerImages(baseUrl, layers) {
  const pairs = await Promise.all(
    layers.map(async (layer) => [layer.id, await loadImage(`${baseUrl}/${layer.file}`)])
  );
  return Object.fromEntries(pairs);
}

function describePack(meta, layers) {
  const bbox = objOrEmpty(meta.bbox);
  const metersPerBlock = meta.meters_per_block;
  const metersText =
    metersPerBlock === null || metersPerBlock === undefined ? "" : `~${esc(metersPerBlock)} m/sample`;
  els.titleHud.textContent = strOrEmpty(meta.name) || "RealEarth";
  els.packInfo.innerHTML = [
    `<strong>${esc(strOrEmpty(meta.name)) || "pack"}</strong>`,
    `bbox ${fmt(bbox.west)}°,${fmt(bbox.south)}° → ${fmt(bbox.east)}°,${fmt(bbox.north)}°`,
    `samples ${esc(meta.sample_width)}×${esc(meta.sample_height)}${meta.view_width ? ` · view ${esc(meta.view_width)}×${esc(meta.view_height)}` : ""}`,
    metersText,
    `${numOrZero(meta.settlement_count)} settlements · ${layers.length} tiles`,
  ]
    .filter(Boolean)
    .join("<br/>");
}

async function loadPack(baseUrl) {
  setStatus("Loading pack…");
  state.baseUrl = baseUrl.replace(/\/$/u, "");
  const metaUrl = `${state.baseUrl}/viewer.json`;
  const res = await fetch(metaUrl);
  if (!res.ok) {
    throw new Error(`Cannot load ${metaUrl} (${res.status})`);
  }
  const meta = await res.json();
  state.meta = meta;

  fillLayers(meta);
  const layers = listOrEmpty(meta.layers);
  describePack(meta, layers);

  // viewer.json only names the artifacts; fetch them all in parallel instead of
  // a meta → settlements → image-per-image → elev chain.
  const elevMeta = objOrEmpty(meta.elev_raw);
  state.elevMeta = elevMeta.file ? elevMeta : null;
  const [settlements, images, elevRaw] = await Promise.all([
    fetchSettlements(state.baseUrl),
    fetchLayerImages(state.baseUrl, layers),
    fetchElevationRaw(state.baseUrl, state.elevMeta),
  ]);
  state.settlements = settlements;
  state.images = images;
  state.elevRaw = elevRaw;

  applyLayer();
  setStatus(readyStatus());
}

function fmt(n) {
  if (n === null || n === undefined || Number.isNaN(n)) {
    return "?";
  }
  return Number(n).toFixed(2);
}

function applyLayer() {
  const img = state.images[state.layerId] || Object.values(state.images)[0];
  if (!img || !state.meta) {
    return;
  }
  renderLegend(state.layerId);

  if (state.mode === "flat") {
    ensureMap2D();
    state.map2d.setImage(img, {
      bbox: state.meta.bbox,
      settlements: state.settlements,
      tileSize: state.meta.tile_size,
      sampleWidth: state.meta.sample_width,
      sampleHeight: state.meta.sample_height,
    });
    state.map2d.setLayerFlags({
      showSettlements: els.showSettlements.checked,
      showGrid: els.showGrid.checked,
      opacity: Number(els.opacity.value),
    });
    return;
  }
  showOnGlobe(img);
}

// Globe mode pulls three.js from the CDN on first use; until it resolves the
// HUD says so, and a failed import reports and falls back to the flat map
// instead of leaving a dead globe host.
function showOnGlobe(img) {
  setStatus("Loading globe…");
  ensureGlobe()
    .then((globe) => {
      if (!globe || state.mode !== "globe") {
        return;
      }
      // re-measure in case the stage resized while flat mode was showing
      globe.resize();
      globe.setTexture(
        img,
        els.showSettlements.checked ? state.settlements : [],
        state.meta.bbox
      );
      setStatus(readyStatus());
    })
    .catch((error) => {
      // drop the failed import so the next Globe click retries the fetch
      state.globeReady = null;
      setStatus(errorMessage(error));
      setMode("flat");
    });
}

function ensureMap2D() {
  if (!state.map2d) {
    state.map2d = new Map2D(els.mapCanvas);
    state.map2d.onProbe = (p) => updateProbe(p);
    state.map2d.onHoverSettlement = (s, sx, sy) => showTip(s, sx, sy);
  }
  els.mapCanvas.hidden = false;
  els.globeHost.hidden = true;
  state.map2d.resize();
}

function ensureGlobe() {
  els.mapCanvas.hidden = true;
  els.globeHost.hidden = false;
  if (!state.globeReady) {
    state.globeReady = import("./globe.js").then((module) => {
      const globe = new module.GlobeView(els.globeHost);
      globe.resize();
      return globe;
    });
  }
  return state.globeReady;
}

function updateProbe(p) {
  if (!p) {
    els.pLon.textContent = "—";
    els.pLat.textContent = "—";
    els.pElev.textContent = "—";
    els.pUv.textContent = "—";
    return;
  }
  els.pLon.textContent = `${p.lon.toFixed(5)}°`;
  els.pLat.textContent = `${p.lat.toFixed(5)}°`;
  els.pUv.textContent = `${p.u.toFixed(3)}, ${p.v.toFixed(3)}`;

  let elevText = "—";
  if (state.elevRaw && state.elevMeta) {
    const x = Math.min(state.elevRaw.w - 1, Math.max(0, Math.floor(p.u * state.elevRaw.w)));
    const y = Math.min(state.elevRaw.h - 1, Math.max(0, Math.floor(p.v * state.elevRaw.h)));
    const pix = state.elevRaw.ctx.getImageData(x, y, 1, 1).data;
    // PNG 16-bit may be read as 8-bit per channel in canvas; use red as coarse proxy if needed
    // Prefer luminance of exported elevation_raw (16-bit becomes dual-byte in some browsers).
    // Our export is single-channel I;16; browsers often expand. Fall back to R channel scale.
    const t = pix[0] / 255;
    const elev = numOrZero(state.elevMeta.offset_m) + t * (numOrZero(state.elevMeta.scale_m) || 4500);
    elevText = `${elev.toFixed(0)} m (approx)`;
  }
  els.pElev.textContent = elevText;
}

function showTip(s, sx, sy) {
  if (!s) {
    els.settlementTip.hidden = true;
    return;
  }
  els.settlementTip.hidden = false;
  els.settlementTip.style.left = `${sx}px`;
  els.settlementTip.style.top = `${sy}px`;
  const population =
    s.population === null || s.population === undefined ? "?" : s.population.toLocaleString();
  els.settlementTip.innerHTML = `<strong>${esc(s.name)}</strong><br/>${esc(strOrEmpty(s.band))} · pop ${esc(population)}<br/>${esc(s.lat?.toFixed?.(3))}°, ${esc(s.lon?.toFixed?.(3))}°`;
}

function setMode(mode) {
  state.mode = mode;
  els.btnFlat.classList.toggle("active", mode === "flat");
  els.btnGlobe.classList.toggle("active", mode === "globe");
  applyLayer();
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
  if (state.map2d) {
    state.map2d.setLayerFlags({ showGrid: els.showGrid.checked });
  }
});
els.opacity.addEventListener("input", () => {
  if (state.map2d) {
    state.map2d.setLayerFlags({ opacity: Number(els.opacity.value) });
  }
});
els.packSelect.addEventListener("change", () => {
  loadPack(els.packSelect.value).catch((error) => {
    setStatus(errorMessage(error));
    els.packInfo.textContent = errorMessage(error);
  });
});

els.jsonFile.addEventListener("change", () => {
  const file = els.jsonFile.files?.[0];
  if (!file) {
    return;
  }
  // File picker only gives viewer.json; sibling images must be same-folder via directory not available.
  // Support loading meta + ask user that export folder should be served over HTTP.
  file
    .text()
    .then((text) => JSON.parse(text))
    .then((meta) => {
      // If user picked a file, try relative to a blob base by reading nothing else —
      // instead prompt to use served packs.
      setStatus("Use a served pack path for full layers. Meta only loaded for preview.");
      state.meta = meta;
      fillLayers(meta);
      els.packInfo.textContent =
        "Loaded viewer.json from disk. Serve the export folder over HTTP and pick it in Dataset for images.";
    })
    .catch((error) => {
      setStatus(errorMessage(error));
    });
});

// discover extra packs if catalog exists
async function boot() {
  const params = new URLSearchParams(location.search);
  const pack = params.get("pack") || els.packSelect.value;
  // catalog and the initial pack are independent: fetch both at once
  const [catalog] = await Promise.all([
    fetch("data/catalog.json").catch(() => null),
    loadPack(pack).catch((error) => {
      setStatus(`Cannot load ${pack}: ${errorMessage(error)}`);
      els.packInfo.innerHTML =
        `Missing or broken <code>${esc(pack)}/viewer.json</code>.<br/>` +
        `From repo: <code>realearth export-viewer --pack data/samples/demo_region --out viewer/data/demo</code><br/>` +
        `then <code>realearth serve</code>`;
    }),
  ]);
  if (catalog && catalog.ok) {
    const list = await catalog.json();
    for (const item of list) {
      const opt = document.createElement("option");
      opt.value = item.path;
      opt.textContent = item.name || item.path;
      els.packSelect.append(opt);
    }
  }
  els.packSelect.value = pack;
}

await boot();
