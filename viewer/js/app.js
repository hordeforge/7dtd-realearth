import { Map2D } from "./map2d.js";
import { GlobeView } from "./globe.js";

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

const els = {
  packSelect: document.getElementById("packSelect"),
  jsonFile: document.getElementById("jsonFile"),
  packInfo: document.getElementById("packInfo"),
  layerSelect: document.getElementById("layerSelect"),
  showSettlements: document.getElementById("showSettlements"),
  showGrid: document.getElementById("showGrid"),
  opacity: document.getElementById("opacity"),
  legend: document.getElementById("legend"),
  btnFlat: document.getElementById("btnFlat"),
  btnGlobe: document.getElementById("btnGlobe"),
  mapCanvas: document.getElementById("mapCanvas"),
  globeHost: document.getElementById("globeHost"),
  titleHud: document.getElementById("titleHud"),
  statusHud: document.getElementById("statusHud"),
  settlementTip: document.getElementById("settlementTip"),
  pLon: document.getElementById("pLon"),
  pLat: document.getElementById("pLat"),
  pElev: document.getElementById("pElev"),
  pUv: document.getElementById("pUv"),
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
  globe: null,
};

function setStatus(msg) {
  els.statusHud.textContent = msg;
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
  for (const layer of meta.layers || []) {
    const opt = document.createElement("option");
    opt.value = layer.id;
    opt.textContent = layer.label || layer.id;
    els.layerSelect.appendChild(opt);
  }
  if (meta.layers?.length) {
    state.layerId = meta.layers[0].id;
    els.layerSelect.value = state.layerId;
  }
  renderLegend(state.layerId);
}

async function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`failed to load ${url}`));
    img.src = url;
  });
}

async function loadPack(baseUrl) {
  setStatus("Loading pack…");
  state.baseUrl = baseUrl.replace(/\/$/, "");
  const metaUrl = `${state.baseUrl}/viewer.json`;
  const res = await fetch(metaUrl);
  if (!res.ok) throw new Error(`Cannot load ${metaUrl} (${res.status})`);
  const meta = await res.json();
  state.meta = meta;

  fillLayers(meta);
  els.titleHud.textContent = meta.name || "RealEarth";
  const bbox = meta.bbox || {};
  els.packInfo.innerHTML = [
    `<strong>${meta.name || "pack"}</strong>`,
    `bbox ${fmt(bbox.west)}°,${fmt(bbox.south)}° → ${fmt(bbox.east)}°,${fmt(bbox.north)}°`,
    `samples ${meta.sample_width}×${meta.sample_height}` +
      (meta.view_width ? ` · view ${meta.view_width}×${meta.view_height}` : ""),
    meta.meters_per_block != null ? `~${meta.meters_per_block} m/sample` : "",
    `${meta.settlement_count ?? 0} settlements · ${(meta.tiles || []).length} tiles`,
  ]
    .filter(Boolean)
    .join("<br/>");

  // settlements
  state.settlements = [];
  try {
    const sres = await fetch(`${state.baseUrl}/settlements.json`);
    if (sres.ok) state.settlements = await sres.json();
  } catch {
    /* optional */
  }

  // layer images
  state.images = {};
  for (const layer of meta.layers || []) {
    state.images[layer.id] = await loadImage(`${state.baseUrl}/${layer.file}`);
  }

  // raw elev for probe
  state.elevRaw = null;
  state.elevMeta = meta.elev_raw || null;
  if (state.elevMeta?.file) {
    try {
      const img = await loadImage(`${state.baseUrl}/${state.elevMeta.file}`);
      const c = document.createElement("canvas");
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      const ctx = c.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      state.elevRaw = {
        ctx,
        w: c.width,
        h: c.height,
      };
    } catch {
      /* optional */
    }
  }

  applyLayer();
  setStatus(`Loaded · ${meta.layers?.length || 0} layers`);
}

function fmt(n) {
  if (n == null || Number.isNaN(n)) return "?";
  return Number(n).toFixed(2);
}

function currentImage() {
  return state.images[state.layerId] || Object.values(state.images)[0];
}

function applyLayer() {
  const img = currentImage();
  if (!img || !state.meta) return;
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
  } else {
    ensureGlobe();
    state.globe.setTexture(
      img,
      els.showSettlements.checked ? state.settlements : [],
      state.meta.bbox
    );
  }
}

function ensureMap2D() {
  if (!state.map2d) {
    state.map2d = new Map2D(els.mapCanvas);
    state.map2d.onProbe = (p) => updateProbe(p);
    state.map2d.onHoverSettlement = (s, sx, sy) => showTip(s, sx, sy);
  }
  els.mapCanvas.hidden = false;
  els.globeHost.hidden = true;
  if (state.globe) {
    /* keep but hidden */
  }
  state.map2d.resize();
}

function ensureGlobe() {
  els.mapCanvas.hidden = true;
  els.globeHost.hidden = false;
  if (!state.globe) {
    state.globe = new GlobeView(els.globeHost);
  }
  state.globe.resize();
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
    const elev =
      (state.elevMeta.offset_m || 0) + t * (state.elevMeta.scale_m || 4500);
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
  const pop = s.population != null ? s.population.toLocaleString() : "?";
  els.settlementTip.innerHTML = `<strong>${s.name}</strong><br/>${s.band || ""} · pop ${pop}<br/>${s.lat?.toFixed?.(3)}°, ${s.lon?.toFixed?.(3)}°`;
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
els.packSelect.addEventListener("change", async () => {
  try {
    await loadPack(els.packSelect.value);
  } catch (e) {
    setStatus(String(e.message || e));
    els.packInfo.textContent = String(e.message || e);
  }
});

els.jsonFile.addEventListener("change", async () => {
  const file = els.jsonFile.files?.[0];
  if (!file) return;
  try {
    // File picker only gives viewer.json; sibling images must be same-folder via directory not available.
    // Support loading meta + ask user that export folder should be served over HTTP.
    const text = await file.text();
    const meta = JSON.parse(text);
    // If user picked a file, try relative to a blob base by reading nothing else —
    // instead prompt to use served packs.
    setStatus("Use a served pack path for full layers. Meta only loaded for preview.");
    state.meta = meta;
    fillLayers(meta);
    els.packInfo.textContent =
      "Loaded viewer.json from disk. Serve the export folder over HTTP and pick it in Dataset for images.";
  } catch (e) {
    setStatus(String(e.message || e));
  }
});

// discover extra packs if catalog exists
async function boot() {
  try {
    const cat = await fetch("data/catalog.json");
    if (cat.ok) {
      const list = await cat.json();
      for (const item of list) {
        const opt = document.createElement("option");
        opt.value = item.path;
        opt.textContent = item.name || item.path;
        els.packSelect.appendChild(opt);
      }
    }
  } catch {
    /* optional */
  }

  const params = new URLSearchParams(location.search);
  const pack = params.get("pack") || els.packSelect.value;
  els.packSelect.value = pack;
  try {
    await loadPack(pack);
  } catch (e) {
    setStatus(`No pack at ${pack}. Run: realearth export-viewer && realearth serve`);
    els.packInfo.innerHTML =
      `Missing <code>${pack}/viewer.json</code>.<br/>` +
      `From repo: <code>realearth export-viewer --pack data/samples/demo_region --out viewer/data/demo</code><br/>` +
      `then <code>realearth serve</code>`;
  }
}

boot();
