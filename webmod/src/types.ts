// Shared types for the RealEarth webmod.
//
// Data shapes (Bbox, PackMeta, Settlement, ...) describe the output of
// `realearth export-viewer`; optional or missing fields are coerced to
// concrete defaults at parse time in pack.ts so consumers never handle
// undefined. Dashboard types (ReactApi, WebModComponentProps, WebModExports)
// describe the small slice of the stock 7dtd dashboard API that this webmod
// relies on (see webmod/README.md "Integration contract").

export type Bbox = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export type LayerInfo = {
  id: string;
  file: string;
  label: string;
};

export type ElevRawMeta = {
  file: string;
  offset_m: number;
  scale_m: number;
};

export type PackMeta = {
  name: string;
  version: number;
  bbox: Bbox;
  sample_width: number;
  sample_height: number;
  view_width: number;
  view_height: number;
  scale: number;
  tile_size: number;
  meters_per_block: number;
  world_width: number;
  world_height: number;
  sea_level_game_y: number;
  tiles: Array<unknown>;
  sources: Array<string>;
  notes: string;
  layers: Array<LayerInfo>;
  settlement_count: number;
  elev_raw: ElevRawMeta | null;
};

export type Settlement = {
  name: string;
  lon: number;
  lat: number;
  population: number;
  band: string;
  edge_radius_m: number;
  edge_source: string;
};

export type ProbePoint = {
  lon: number;
  lat: number;
  u: number;
  v: number;
  ix: number;
  iy: number;
};

export type KeyValueEntry = {
  name: string;
  type: string;
  value: string;
};

// --- stock dashboard injection ---

// Minimal typed view of the dashboard's React instance. The dashboard renders
// each registered component with its own React plus helpers (styled, HTTP,
// tables, forms); this webmod only uses React and builds the UI with
// createElement, so the remaining props are intentionally left untyped.
export type ReactApi = {
  createElement: (
    type: unknown,
    props: Record<string, unknown> | null,
    ...children: Array<unknown>
  ) => unknown;
  useState: <T>(initial: T | (() => T)) => [T, (next: T | ((prev: T) => T)) => void];
  useEffect: (effect: () => unknown, deps?: ReadonlyArray<unknown>) => void;
  useRef: <T>(initial: T) => { current: T };
};

export type WebModComponentProps = {
  React: ReactApi;
};

export type WebModExports = {
  routes: Record<string, (props: WebModComponentProps) => unknown>;
  settings: Record<string, (props: WebModComponentProps) => unknown>;
};

export type ElementFactory = (
  type: string,
  props: Record<string, unknown> | null,
  ...children: Array<unknown>
) => unknown;

export function makeElement(react: ReactApi): ElementFactory {
  return (type, props, ...children) => react.createElement(type, props, ...children);
}
