// Shared types for the standalone map viewer.
//
// Data shapes (Bbox, PackMeta, Settlement, ...) describe the output of
// `realearth export-viewer`; optional or missing JSON fields are coerced to
// concrete defaults at parse time in pack.ts so consumers never handle
// undefined. Mirrors ../webmod/src/types.ts; keep both in sync when the
// export format changes.

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

// Entry of the served data/catalog.json listing extra packs.
export type CatalogEntry = {
  path: string;
  name: string;
};
