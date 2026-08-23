// Per-layer legend rows shown next to the map. The colors mirror the palette
// the offline pipeline bakes into each layer PNG (tools/realearth viewer
// export); keep them in sync when the export palette changes.

export type LegendRow = {
  color: string;
  label: string;
};

// The fallback lives outside the Record so its type stays concrete under
// noUncheckedIndexedAccess (index-signature lookups are T | undefined).
const HYBRID_LEGEND: ReadonlyArray<LegendRow> = [
  { color: "#3dd6c6", label: "Terrain + cover blend" },
  { color: "#f0a500", label: "Settlement markers" },
];

const LEGENDS: Record<string, ReadonlyArray<LegendRow>> = {
  elevation: [
    { color: "#0a285a", label: "Deep / ocean" },
    { color: "#2d6b3a", label: "Lowland" },
    { color: "#8b6b3a", label: "Upland" },
    { color: "#d8d8d8", label: "High peaks" },
  ],
  landcover: [
    { color: "#0000ff", label: "Ocean" },
    { color: "#004000", label: "Forest" },
    { color: "#ffff00", label: "Desert" },
    { color: "#ffffff", label: "Snow/ice" },
    { color: "#ff0000", label: "Urban" },
    { color: "#808080", label: "Barren" },
  ],
  population: [
    { color: "#0c0c12", label: "None" },
    { color: "#c8a020", label: "Low" },
    { color: "#f07020", label: "Medium" },
    { color: "#ff2020", label: "High" },
  ],
  hybrid: HYBRID_LEGEND,
};

export function legendFor(layerId: string): ReadonlyArray<LegendRow> {
  return LEGENDS[layerId] ?? HYBRID_LEGEND;
}
