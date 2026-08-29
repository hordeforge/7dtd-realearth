// Streamed elevation layer: render .rte tiles to a canvas as relief.
//
// The classic viewer path ships pre-made PNG mosaics (hybrid.png etc.);
// this layer fetches raw .rte tiles on demand and draws elevation to a
// canvas, so packs too large for one mosaic still render. Tiles are drawn
// in pack order (tz/tx) at their natural resolution.

import type { RteTile } from "./rte.js";

export type RteLayerMeta = {
  tileSize: number;
  gridW: number; // tiles across
  gridH: number; // tiles down
  seaLevelGameY: number;
  metersPerBlock: number;
};

const SEA_LEVEL_M = 0; // elevation below this renders as sea
const EVEREST_M = 8849; // top of the land ramp
const SEA_R = 20;
const SEA_G = 60;
const SEA_B = 160;
const LAND_MIN = 60;
const LAND_RANGE = 180;
const ALPHA_OPAQUE = 255;
const CHANNELS = 4;
const ALPHA_INDEX = 3;

function reliefColor(elevM: number, meta: RteLayerMeta): [number, number, number] {
  // Sea below 0 m ASL (pack sea_level_game_y is a game-Y anchor, not meters).
  if (elevM <= SEA_LEVEL_M) {
    return [SEA_R, SEA_G, SEA_B];
  }
  // Land: grayscale ramp over [-1, 8849] m; meters-per-block only changes
  // horizontal sampling, not the ramp.
  void meta;
  const t = Math.min(1, Math.max(0, (elevM - SEA_LEVEL_M) / EVEREST_M));
  const v = Math.round(LAND_MIN + t * LAND_RANGE);
  return [v, v, v];
}

export async function renderRteLayer(
  canvas: HTMLCanvasElement,
  ctx: CanvasRenderingContext2D,
  tiles: ReadonlyArray<RteTile>,
  meta: RteLayerMeta
): Promise<void> {
  canvas.width = meta.gridW * meta.tileSize;
  canvas.height = meta.gridH * meta.tileSize;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (const tile of tiles) {
    const x0 = tile.header.tx * meta.tileSize;
    const y0 = tile.header.tz * meta.tileSize;
    const img = ctx.createImageData(tile.header.width, tile.header.height);
    const px = img.data;
    const elev = tile.elevationM;
    for (let i = 0; i < elev.length; i++) {
      const [r, g, b] = reliefColor(elev[i] ?? 0, meta);
      const o = i * CHANNELS;
      px[o] = r;
      px[o + 1] = g;
      px[o + 2] = b;
      px[o + ALPHA_INDEX] = ALPHA_OPAQUE;
    }
    ctx.putImageData(img, x0, y0);
  }
}
