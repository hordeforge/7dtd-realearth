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
// Pack paths are joined into fetch URLs. They must stay inside the served
// export tree: no absolute paths, no scheme (cross-origin pack injection),
// no backslashes, no dot-dot traversal.
function isSafePackPath(candidate) {
  return (
    typeof candidate === "string" &&
    candidate !== "" &&
    !candidate.startsWith("/") &&
    !candidate.includes("\\") &&
    !/^[a-z][a-z0-9+.-]*:/iu.test(candidate) &&
    !candidate.split("/").includes("..")
  );
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
  els.legend.replaceChildren();
  const rows = LEGENDS[layerId] || LEGENDS.hybrid;
  for (const [legendColor, label] of rows) {
    const row = document.createElement("div");
    row.className = "legend-row";
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    const safeColor =
      typeof legendColor === "string" && /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/u.test(legendColor)
        ? legendColor
        : "#808080";
    swatch.style.background = safeColor;
    row.append(swatch, document.createTextNode(String(label)));
    els.legend.append(row);
  }
}

function fillLayers(meta) {
  els.layerSelect.replaceChildren();
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

function describePack(meta) {
  const bbox = objOrEmpty(meta.bbox);
  const metersPerBlock = meta.meters_per_block;
  const metersText =
    metersPerBlock === null || metersPerBlock === undefined ? "" : `~${String(metersPerBlock)} m/sample`;
  els.titleHud.textContent = strOrEmpty(meta.name) || "RealEarth";
  const tileCount = listOrEmpty(meta.tiles).length;
  const lines = [
    strOrEmpty(meta.name) || "pack",
    `bbox ${fmt(bbox.west)}\u00B0,${fmt(bbox.south)}\u00B0 \u2192 ${fmt(bbox.east)}\u00B0,${fmt(bbox.north)}\u00B0`,
    `samples ${String(meta.sample_width)}\u00D7${String(meta.sample_height)}${meta.view_width ? ` \u00B7 view ${String(meta.view_width)}\u00D7${String(meta.view_height)}` : ""}`,
    metersText,
    `${String(numOrZero(meta.settlement_count))} settlements \u00B7 ${String(tileCount)} tiles`,
  ].filter(Boolean);
  els.packInfo.replaceChildren();
  for (let i = 0; i < lines.length; i += 1) {
    if (i === 0) {
      const strong = document.createElement("strong");
      strong.textContent = lines[i];
      els.packInfo.append(strong);
    } else {
      els.packInfo.append(document.createTextNode(lines[i]));
    }
    if (i < lines.length - 1) {
      els.packInfo.append(document.createElement("br"));
    }
  }
}

async function loadPack(baseUrl) {
  if (!isSafePackPath(baseUrl)) {
    throw new Error(`Refusing unsafe pack path: ${String(baseUrl)}`);
  }
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
  describePack(meta);

  // viewer.json only names the artifacts; fetch them all in parallel instead of
  // a meta → settlements → image-per-image → elev chain.
  const elevMeta = objOrEmpty(meta.elev_raw);
  state.elevMeta = elevMeta.file ? elevMeta : null;
  const [settlements, images, elevRaw] = await Promise.all([
    // optional sibling artifact; absence is not a failure
    fetch(`${state.baseUrl}/settlements.json`)
      .then((response) => (response && response.ok ? response.json() : []))
      .catch(() => []),
    Promise.all(
      listOrEmpty(meta.layers).map(async (layer) => [
        layer.id,
        await loadImage(`${state.baseUrl}/${layer.file}`),
      ])
    ).then(Object.fromEntries),
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
  // Globe mode pulls three.js from the CDN on first use; until it resolves the
  // HUD says so, and a failed import reports and falls back to the flat map
  // instead of leaving a dead globe host.
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
    // Exported elevation_raw is single-channel I;16 but canvas often decodes it
    // as one 8-bit byte per pixel; the first channel is a coarse height proxy.
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
  els.settlementTip.replaceChildren();
  const strong = document.createElement("strong");
  const settlementName = typeof s.name === "string" ? s.name : "";
  strong.textContent = settlementName;
  els.settlementTip.append(strong);
  els.settlementTip.append(document.createElement("br"));
  els.settlementTip.append(document.createTextNode(`${String(strOrEmpty(s.band))} \u00B7 pop ${String(population)}`));
  els.settlementTip.append(document.createElement("br"));
  els.settlementTip.append(document.createTextNode(`${String(s.lat?.toFixed?.(3) ?? "?")}\u00B0, ${String(s.lon?.toFixed?.(3) ?? "?")}\u00B0`));
}

function setMode(mode) {
  state.mode = mode;
  els.btnFlat.classList.toggle("active", mode === "flat");
  els.btnGlobe.classList.toggle("active", mode === "globe");
  els.btnFlat.setAttribute("aria-pressed", String(mode === "flat"));
  els.btnGlobe.setAttribute("aria-pressed", String(mode === "globe"));
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
  // A crafted ?pack= link must not point the viewer at other origins or
  // outside the served tree; unsafe values fall back to the bundled pack.
  const requested = params.get("pack");
  const pack = isSafePackPath(requested) ? requested : els.packSelect.value;
  const [catalog] = await Promise.all([
    fetch("data/catalog.json").catch(() => null),
    loadPack(pack).catch((error) => {
      setStatus(`Cannot load ${pack}: ${errorMessage(error)}`);
      els.packInfo.replaceChildren();
      els.packInfo.append(document.createTextNode(`Missing or broken ${String(pack)}/viewer.json.`));
      els.packInfo.append(document.createElement("br"));
      const hint1 = document.createElement("code");
      hint1.textContent = "realearth export-viewer --pack data/samples/demo_region --out viewer/data/demo";
      els.packInfo.append(document.createTextNode("From repo: "), hint1);
      els.packInfo.append(document.createElement("br"));
      const hint2 = document.createElement("code");
      hint2.textContent = "realearth serve";
      els.packInfo.append(document.createTextNode("then "), hint2);
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
