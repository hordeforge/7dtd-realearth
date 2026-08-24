// Overview route page: the loaded pack's metadata plus a live server-stats
// card from the stock dashboard API. Shares the loaded pack with the Map page
// through packStore, so opening Overview after loading a pack on Map shows the
// same dataset.

import { MOD_BASE_URL } from "./base";
import { asRecord, asString, errorMessage } from "./coerce";
import { packStore } from "./store";
import type { KeyValueEntry, WebModComponentProps, ElementFactory } from "./types";
import type { LoadedPack } from "./pack";
import { makeElement } from "./types";

const API_STATS_URL = "/api/serverstats";
const COORD_PRECISION = 2;

function displayValue(candidate: unknown): string {
  if (typeof candidate === "string") {
    return candidate;
  }
  if (typeof candidate === "number" && Number.isFinite(candidate)) {
    return String(candidate);
  }
  if (typeof candidate === "boolean") {
    return candidate ? "true" : "false";
  }
  return "";
}

function keyValueListFrom(candidate: unknown): Array<KeyValueEntry> {
  if (!Array.isArray(candidate)) {
    return [];
  }
  const entries: Array<KeyValueEntry> = [];
  for (const item of candidate) {
    const record = asRecord(item);
    const name = asString(record.name);
    if (name !== "") {
      entries.push({ name, type: asString(record.type), value: displayValue(record.value) });
    }
  }
  return entries;
}

async function fetchKeyValues(url: string): Promise<Array<KeyValueEntry>> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Server API ${url} failed (HTTP ${response.status})`);
  }
  const envelope = asRecord(await response.json());
  return keyValueListFrom(envelope.data);
}

function fmtCoord(coordinate: number): string {
  return coordinate.toFixed(COORD_PRECISION);
}

function infoRow(h: ElementFactory, key: string, text: string): unknown {
  return h("div", { className: "re-info-row" }, h("dt", null, key), h("dd", null, text));
}

function infoList(h: ElementFactory, rows: Array<readonly [string, string]>): unknown {
  const children: Array<unknown> = [];
  for (const [key, value] of rows) {
    children.push(infoRow(h, key, value));
  }
  return h("dl", { className: "re-info" }, ...children);
}

function packCard(h: ElementFactory, pack: LoadedPack | null): unknown {
  if (pack === null) {
    return h(
      "section",
      { className: "re-panel" },
      h("h2", null, "Pack"),
      h("p", { className: "re-muted" }, "No pack loaded. Open the Map page to load one.")
    );
  }
  const { meta } = pack;
  const rows: Array<readonly [string, string]> = [
    ["Name", meta.name === "" ? "(unnamed)" : meta.name],
    ["Path", pack.path],
    [
      "BBox",
      `${fmtCoord(meta.bbox.west)} to ${fmtCoord(meta.bbox.east)} lon, ${fmtCoord(meta.bbox.south)} to ${fmtCoord(meta.bbox.north)} lat`,
    ],
    ["Samples", `${meta.sample_width} x ${meta.sample_height}`],
    ["View", `${meta.view_width} x ${meta.view_height}`],
    ["Scale", fmtCoord(meta.scale)],
    ["Meters/sample", fmtCoord(meta.meters_per_block)],
    ["World (blocks)", `${meta.world_width} x ${meta.world_height}`],
    ["Sea level (game y)", String(meta.sea_level_game_y)],
    ["Tiles", String(meta.tiles.length)],
    ["Settlements", String(meta.settlement_count)],
    ["Elevation probe", pack.elevRaw === null ? "not exported" : "raw PNG"],
  ];
  return h("section", { className: "re-panel" }, h("h2", null, "Pack"), infoList(h, rows));
}

function layersCard(h: ElementFactory, pack: LoadedPack | null): unknown {
  if (pack === null) {
    return null;
  }
  const children: Array<unknown> = [];
  for (const layer of pack.meta.layers) {
    children.push(
      h(
        "li",
        { className: "re-layer" },
        h("span", { className: "re-layer-id" }, layer.id),
        h("span", { className: "re-muted" }, layer.file)
      )
    );
  }
  return h(
    "section",
    { className: "re-panel" },
    h("h2", null, `Layers (${pack.meta.layers.length})`),
    h("ul", { className: "re-layers" }, ...children)
  );
}

function notesCard(h: ElementFactory, pack: LoadedPack | null): unknown {
  if (pack === null) {
    return null;
  }
  const children: Array<unknown> = [];
  if (pack.meta.notes !== "") {
    children.push(h("p", { className: "re-note" }, pack.meta.notes));
  }
  if (pack.meta.sources.length > 0) {
    children.push(h("p", { className: "re-muted" }, `Sources: ${pack.meta.sources.join(", ")}`));
  }
  if (pack.warnings.length > 0) {
    children.push(h("p", { className: "re-warning" }, pack.warnings.join("; ")));
  }
  if (children.length === 0) {
    return null;
  }
  return h("section", { className: "re-panel" }, h("h2", null, "Notes"), ...children);
}

function statsCard(h: ElementFactory, stats: Array<KeyValueEntry> | null, statsError: string): unknown {
  const heading = h("h2", null, "Server stats");
  if (statsError !== "") {
    return h(
      "section",
      { className: "re-panel" },
      heading,
      h("p", { className: "re-warning" }, statsError)
    );
  }
  if (stats === null) {
    return h(
      "section",
      { className: "re-panel" },
      heading,
      h("p", { className: "re-muted" }, "Loading...")
    );
  }
  if (stats.length === 0) {
    return h(
      "section",
      { className: "re-panel" },
      heading,
      h("p", { className: "re-muted" }, "No stats returned.")
    );
  }
  const rows: Array<readonly [string, string]> = [];
  for (const entry of stats) {
    rows.push([entry.name, entry.value]);
  }
  return h("section", { className: "re-panel" }, heading, infoList(h, rows));
}

export function OverviewPage(props: WebModComponentProps): unknown {
  const { React } = props;
  const h: ElementFactory = makeElement(React);
  const [pack, setPack] = React.useState<LoadedPack | null>(packStore.get());
  const [stats, setStats] = React.useState<Array<KeyValueEntry> | null>(null);
  const [statsError, setStatsError] = React.useState("");

  React.useEffect(() => {
    // Subscribe before pulling: a load resolving between this render and the
    // effect would otherwise notify zero subscribers and leave the stale
    // "No pack loaded" snapshot on screen.
    const unsubscribe = packStore.subscribe(() => setPack(packStore.get()));
    setPack(packStore.get());
    return unsubscribe;
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    void fetchKeyValues(API_STATS_URL)
      .then((entries) => {
        if (!cancelled) {
          setStats(entries);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setStatsError(errorMessage(error));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return h(
    "div",
    { className: "re-overview" },
    h(
      "div",
      { className: "re-card-grid" },
      packCard(h, pack),
      layersCard(h, pack),
      statsCard(h, stats, statsError),
      notesCard(h, pack)
    ),
    h("p", { className: "re-muted" }, `Data served from ${MOD_BASE_URL}data/ (make webmod-export).`)
  );
}
