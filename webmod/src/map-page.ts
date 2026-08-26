// Map route page. Renders the active pack on a canvas (Map2D) with layer
// select, settlements/grid toggles, opacity, legend, cursor probe, and a pack
// path input. The dashboard injects React (WebMod contract), so this page is
// a thin React shell over imperative DOM wiring, mirroring the standalone
// viewer's interaction model.

import { MOD_BASE_URL } from "./base";
import { errorMessage } from "./coerce";
import { legendFor } from "./legend";
import { Map2D } from "./map2d";
import type { MapFlags } from "./map2d";
import { loadPack } from "./pack";
import type { LoadedPack } from "./pack";
import { getDefaultPackPath } from "./settings-store";
import { packStore } from "./store";
import type { ElementFactory, ProbePoint, ReactApi, Settlement, WebModComponentProps } from "./types";
import { makeElement } from "./types";

const PROBE_COORD_PRECISION = 5;
const PROBE_UV_PRECISION = 3;
const COORD_PRECISION = 2;
const BYTE_MAX = 255;
const DASH = "-";

type MapPageRefs = {
  map: { current: Map2D | null };
  canvas: { current: HTMLCanvasElement | null };
  packInput: { current: HTMLInputElement | null };
  loadButton: { current: HTMLButtonElement | null };
  layerSelect: { current: HTMLSelectElement | null };
  settlements: { current: HTMLInputElement | null };
  grid: { current: HTMLInputElement | null };
  opacity: { current: HTMLInputElement | null };
  legend: { current: HTMLDivElement | null };
  probe: { current: HTMLDivElement | null };
  tip: { current: HTMLDivElement | null };
  packInfo: { current: HTMLDivElement | null };
  status: { current: HTMLSpanElement | null };
};

function makeRefs(React: ReactApi): MapPageRefs {
  return {
    map: React.useRef<Map2D | null>(null),
    canvas: React.useRef<HTMLCanvasElement | null>(null),
    packInput: React.useRef<HTMLInputElement | null>(null),
    loadButton: React.useRef<HTMLButtonElement | null>(null),
    layerSelect: React.useRef<HTMLSelectElement | null>(null),
    settlements: React.useRef<HTMLInputElement | null>(null),
    grid: React.useRef<HTMLInputElement | null>(null),
    opacity: React.useRef<HTMLInputElement | null>(null),
    legend: React.useRef<HTMLDivElement | null>(null),
    probe: React.useRef<HTMLDivElement | null>(null),
    tip: React.useRef<HTMLDivElement | null>(null),
    packInfo: React.useRef<HTMLDivElement | null>(null),
    status: React.useRef<HTMLSpanElement | null>(null),
  };
}

function setText(element: HTMLElement | null, text: string): void {
  if (element !== null) {
    element.textContent = text;
  }
}

function setStatusText(ref: { current: HTMLSpanElement | null }, text: string): void {
  if (ref.current !== null) {
    ref.current.textContent = text;
  }
}

function initialPackPath(): string {
  const fromQuery = new URLSearchParams(globalThis.location.search).get("pack");
  if (fromQuery !== null && fromQuery !== "") {
    return fromQuery;
  }
  return getDefaultPackPath();
}

function elevationText(pack: LoadedPack | null, point: ProbePoint): string {
  if (pack === null || pack.elevRaw === null || pack.elevMeta === null) {
    return DASH;
  }
  const elev = pack.elevRaw;
  const x = Math.min(elev.width - 1, Math.max(0, Math.trunc(point.u * elev.width)));
  const y = Math.min(elev.height - 1, Math.max(0, Math.trunc(point.v * elev.height)));
  const { data } = elev.ctx.getImageData(x, y, 1, 1);
  const t = (data[0] ?? 0) / BYTE_MAX;
  const meters = pack.elevMeta.offset_m + t * pack.elevMeta.scale_m;
  return `${meters.toFixed(0)} m (approx)`;
}

function updateProbe(
  probeEl: HTMLElement | null,
  point: ProbePoint | null,
  pack: LoadedPack | null
): void {
  if (probeEl === null) {
    return;
  }
  const lonEl = probeEl.querySelector<HTMLElement>(".re-probe-lon");
  const latEl = probeEl.querySelector<HTMLElement>(".re-probe-lat");
  const elevEl = probeEl.querySelector<HTMLElement>(".re-probe-elev");
  const uvEl = probeEl.querySelector<HTMLElement>(".re-probe-uv");
  if (point === null) {
    setText(lonEl, DASH);
    setText(latEl, DASH);
    setText(elevEl, DASH);
    setText(uvEl, DASH);
    return;
  }
  setText(lonEl, `${point.lon.toFixed(PROBE_COORD_PRECISION)} deg`);
  setText(latEl, `${point.lat.toFixed(PROBE_COORD_PRECISION)} deg`);
  setText(uvEl, `${point.u.toFixed(PROBE_UV_PRECISION)}, ${point.v.toFixed(PROBE_UV_PRECISION)}`);
  setText(elevEl, elevationText(pack, point));
}

function updateTip(
  tipEl: HTMLElement | null,
  settlement: Settlement | null,
  sx: number,
  sy: number
): void {
  if (tipEl === null) {
    return;
  }
  if (settlement === null) {
    tipEl.hidden = true;
    return;
  }
  tipEl.hidden = false;
  tipEl.style.left = `${sx}px`;
  tipEl.style.top = `${sy}px`;
  const population =
    settlement.population > 0 ? settlement.population.toLocaleString() : "unknown";
  tipEl.replaceChildren(
    document.createTextNode(`${settlement.name} · ${settlement.band} · pop ${population}`)
  );
}

function fillLayerOptions(select: HTMLSelectElement, pack: LoadedPack): void {
  select.replaceChildren();
  for (const layer of pack.meta.layers) {
    const option = document.createElement("option");
    option.value = layer.id;
    option.textContent = layer.label === "" ? layer.id : layer.label;
    select.append(option);
  }
}

function legendRow(color: string, label: string): HTMLElement {
  const row = document.createElement("div");
  row.className = "re-legend-row";
  const swatch = document.createElement("span");
  swatch.className = "re-swatch";
  swatch.style.backgroundColor = color;
  row.append(swatch, document.createTextNode(label));
  return row;
}

function renderLegend(legendEl: HTMLElement | null, layerId: string): void {
  if (legendEl === null) {
    return;
  }
  const rows = legendFor(layerId);
  const children: Array<HTMLElement> = [];
  for (const row of rows) {
    children.push(legendRow(row.color, row.label));
  }
  legendEl.replaceChildren(...children);
}

function fmtCoord(coordinate: number): string {
  return coordinate.toFixed(COORD_PRECISION);
}

function renderPackInfo(infoEl: HTMLElement | null, pack: LoadedPack): void {
  if (infoEl === null) {
    return;
  }
  const { meta } = pack;
  const lines = [
    `Pack: ${meta.name === "" ? "(unnamed)" : meta.name}`,
    `Path: ${pack.path}`,
    `BBox: ${fmtCoord(meta.bbox.west)} to ${fmtCoord(meta.bbox.east)} lon, ${fmtCoord(meta.bbox.south)} to ${fmtCoord(meta.bbox.north)} lat`,
    `Samples: ${meta.sample_width} x ${meta.sample_height}`,
    `Layers: ${meta.layers.length}`,
    `Settlements: ${meta.settlement_count}`,
    `Meters/sample: ${fmtCoord(meta.meters_per_block)}`,
  ];
  const body = pack.warnings.length > 0 ? lines.concat(pack.warnings).join("\n") : lines.join("\n");
  infoEl.replaceChildren(document.createTextNode(body));
}

function readFlags(
  settlements: HTMLInputElement | null,
  grid: HTMLInputElement | null,
  opacity: HTMLInputElement | null
): MapFlags {
  return {
    showSettlements: settlements === null ? true : settlements.checked,
    showGrid: grid === null ? false : grid.checked,
    opacity: opacity === null ? 1 : Number(opacity.value),
  };
}

function applyLayer(map: Map2D, pack: LoadedPack, layerId: string): void {
  const layer = pack.layers.find((candidate) => candidate.id === layerId) ?? pack.layers[0];
  if (layer === undefined) {
    return;
  }
  map.setImage(layer.image, {
    bbox: pack.meta.bbox,
    settlements: pack.settlements,
    tileSize: pack.meta.tile_size,
    sampleWidth: pack.meta.sample_width,
    sampleHeight: pack.meta.sample_height,
  });
}

function createLayerListener(refs: MapPageRefs): () => void {
  return () => {
    const current = refs.map.current;
    const select = refs.layerSelect.current;
    const loaded = packStore.get();
    if (current === null || select === null || loaded === null) {
      return;
    }
    applyLayer(current, loaded, select.value);
    renderLegend(refs.legend.current, select.value);
  };
}

function createToggleListener(
  refs: MapPageRefs,
  flag: "showSettlements" | "showGrid"
): () => void {
  return () => {
    const current = refs.map.current;
    const checkbox = refs[flag === "showSettlements" ? "settlements" : "grid"].current;
    if (current !== null && checkbox !== null) {
      current.setLayerFlags({ [flag]: checkbox.checked });
    }
  };
}

function createOpacityListener(refs: MapPageRefs): () => void {
  return () => {
    const current = refs.map.current;
    const slider = refs.opacity.current;
    if (current !== null && slider !== null) {
      current.setLayerFlags({ opacity: Number(slider.value) });
    }
  };
}

function createPackLoadListener(refs: MapPageRefs, startLoad: (path: string) => void): () => void {
  return () => {
    const input = refs.packInput.current;
    if (input === null) {
      return;
    }
    const next = input.value.trim();
    if (next !== "") {
      startLoad(next);
    }
  };
}

function attachControls(refs: MapPageRefs, startLoad: (path: string) => void): () => void {
  const canvas = refs.canvas.current;
  const layerSelect = refs.layerSelect.current;
  const loadButton = refs.loadButton.current;
  const settlements = refs.settlements.current;
  const grid = refs.grid.current;
  const opacity = refs.opacity.current;
  const packInput = refs.packInput.current;
  if (
    canvas === null ||
    layerSelect === null ||
    loadButton === null ||
    settlements === null ||
    grid === null ||
    opacity === null ||
    packInput === null
  ) {
    return () => undefined;
  }
  const map = new Map2D(canvas);
  refs.map.current = map;
  map.onProbe = (point) => updateProbe(refs.probe.current, point, packStore.get());
  map.onHoverSettlement = (settlement, sx, sy) => updateTip(refs.tip.current, settlement, sx, sy);

  const onLayerChange = createLayerListener(refs);
  const onSettlementsChange = createToggleListener(refs, "showSettlements");
  const onGridChange = createToggleListener(refs, "showGrid");
  const onOpacityChange = createOpacityListener(refs);
  const onLoadClick = createPackLoadListener(refs, startLoad);
  const onPackKeyDown = (event: KeyboardEvent): void => {
    if (event.key === "Enter") {
      event.preventDefault();
      onLoadClick();
    }
  };

  layerSelect.addEventListener("change", onLayerChange);
  settlements.addEventListener("change", onSettlementsChange);
  grid.addEventListener("change", onGridChange);
  opacity.addEventListener("input", onOpacityChange);
  loadButton.addEventListener("click", onLoadClick);
  packInput.addEventListener("keydown", onPackKeyDown);

  return () => {
    layerSelect.removeEventListener("change", onLayerChange);
    settlements.removeEventListener("change", onSettlementsChange);
    grid.removeEventListener("change", onGridChange);
    opacity.removeEventListener("input", onOpacityChange);
    loadButton.removeEventListener("click", onLoadClick);
    packInput.removeEventListener("keydown", onPackKeyDown);
    map.dispose();
  };
}

function renderToolbar(h: ElementFactory, refs: MapPageRefs): unknown {
  return h(
    "div",
    { className: "re-toolbar" },
    h(
      "div",
      { className: "re-field-group" },
      h(
        "label",
        { className: "re-field" },
        h("span", { className: "re-label" }, "Pack"),
        h("input", { ref: refs.packInput, className: "re-input", defaultValue: initialPackPath(), type: "text" })
      ),
      h("button", { ref: refs.loadButton, className: "re-btn", type: "button" }, "Load")
    ),
    h(
      "label",
      { className: "re-field" },
      h("span", { className: "re-label" }, "Layer"),
      h("select", { ref: refs.layerSelect, className: "re-select" })
    ),
    h(
      "label",
      { className: "re-check" },
      h("input", { ref: refs.settlements, type: "checkbox", defaultChecked: true }),
      " Settlements"
    ),
    h(
      "label",
      { className: "re-check" },
      h("input", { ref: refs.grid, type: "checkbox" }),
      " Tile grid"
    ),
    h(
      "label",
      { className: "re-field" },
      h("span", { className: "re-label" }, "Opacity"),
      h("input", { ref: refs.opacity, className: "re-range", type: "range", min: "0.2", max: "1", step: "0.05", defaultValue: "1" })
    ),
    h("span", { ref: refs.status, className: "re-status", role: "status" })
  );
}

function renderStage(h: ElementFactory, refs: MapPageRefs): unknown {
  return h(
    "div",
    { className: "re-stage" },
    h("canvas", {
      ref: refs.canvas,
      className: "re-canvas",
      tabIndex: 0,
      role: "application",
      "aria-label":
        "Interactive map. Focus it and use arrow keys to pan, plus or minus to zoom, Home to fit the view. Mouse users can drag to pan and scroll to zoom.",
    }),
    h("div", { ref: refs.tip, className: "re-tip", hidden: true, role: "tooltip", "aria-live": "polite" })
  );
}

function renderSide(h: ElementFactory, refs: MapPageRefs, loadError: string): unknown {
  return h(
    "aside",
    { className: "re-side" },
    h(
      "section",
      { className: "re-panel" },
      h("h2", null, "Legend"),
      h("div", { ref: refs.legend, className: "re-legend" })
    ),
    h(
      "section",
      { className: "re-panel" },
      h("h2", null, "Cursor"),
      h(
        "dl",
        { ref: refs.probe, className: "re-probe" },
        h("div", null, h("dt", null, "Lon"), h("dd", { className: "re-probe-lon" }, DASH)),
        h("div", null, h("dt", null, "Lat"), h("dd", { className: "re-probe-lat" }, DASH)),
        h("div", null, h("dt", null, "Elev"), h("dd", { className: "re-probe-elev" }, DASH)),
        h("div", null, h("dt", null, "UV"), h("dd", { className: "re-probe-uv" }, DASH))
      )
    ),
    h(
      "section",
      { className: "re-panel" },
      h("h2", null, "Pack"),
      h("div", { ref: refs.packInfo, className: "re-pack-info" })
    ),
    loadError === "" ? null : h("div", { className: "re-error", role: "alert" }, loadError)
  );
}

export function MapPage(props: WebModComponentProps): unknown {
  const { React } = props;
  const h: ElementFactory = makeElement(React);
  const refs = makeRefs(React);
  const [pack, setPack] = React.useState<LoadedPack | null>(null);
  const [loadError, setLoadError] = React.useState("");
  // Monotonic token: when two loads overlap (auto-load plus a manual Load),
  // only the most recently requested one may publish; otherwise a slow older
  // fetch would silently revert the UI to the previous pack.
  const loadGeneration = React.useRef(0);

  const startLoad = (path: string): void => {
    const generation = ++loadGeneration.current;
    setLoadError("");
    setStatusText(refs.status, "Loading...");
    void loadPack(MOD_BASE_URL, path)
      .then((loaded) => {
        if (generation !== loadGeneration.current) {
          return;
        }
        packStore.set(loaded, path);
        setPack(loaded);
        setStatusText(refs.status, `Loaded ${path}`);
      })
      .catch((error: unknown) => {
        if (generation !== loadGeneration.current) {
          return;
        }
        setLoadError(errorMessage(error));
        setStatusText(refs.status, "");
      });
  };

  React.useEffect(() => {
    const detach = attachControls(refs, startLoad);
    setStatusText(refs.status, "Loading...");
    startLoad(initialPackPath());
    return detach;
  }, []);

  React.useEffect(() => {
    if (pack === null) {
      return;
    }
    const map = refs.map.current;
    const layerSelect = refs.layerSelect.current;
    if (map === null || layerSelect === null) {
      return;
    }
    fillLayerOptions(layerSelect, pack);
    const firstLayer = pack.layers[0];
    const selected = firstLayer === undefined ? "" : firstLayer.id;
    layerSelect.value = selected;
    applyLayer(map, pack, selected);
    map.setLayerFlags(readFlags(refs.settlements.current, refs.grid.current, refs.opacity.current));
    renderLegend(refs.legend.current, selected);
    renderPackInfo(refs.packInfo.current, pack);
  }, [pack]);

  return h(
    "div",
    { className: "re-map-page" },
    renderToolbar(h, refs),
    renderStage(h, refs),
    renderSide(h, refs, loadError)
  );
}
