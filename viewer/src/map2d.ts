// Pan/zoom 2D map canvas: draws the active layer PNG, an optional tile grid,
// and settlement markers, and reports cursor probes and hovered settlements.
// Interaction model: drag to pan, scroll wheel to zoom around the cursor,
// two-pointer pinch to zoom, arrow keys to pan, plus/minus to zoom, Home to
// fit. Typed port of the original viewer canvas controller; the dashboard
// variant lives in ../webmod/src/map2d.ts.

import type { Bbox, ProbePoint, Settlement } from "./types.js";

const MAX_DEVICE_PIXEL_RATIO = 2;
const FIT_PADDING_PX = 40;
const MAX_FIT_SCALE = 4;
const MIN_ZOOM = 0.05;
const MAX_ZOOM = 32;
const ZOOM_IN_STEP = 1.12;
const ZOOM_OUT_STEP = 1 / ZOOM_IN_STEP;
const KEY_ZOOM_IN_STEP = 1.25;
const KEY_ZOOM_OUT_STEP = 1 / KEY_ZOOM_IN_STEP;
const PAN_STEP_PX = 60;
const PAN_STEP_LARGE_PX = 160;
const SMOOTH_SCALE_MAX = 3;
const SETTLEMENT_LABEL_MIN_SCALE = 0.6;
const DEFAULT_TILE_SIZE = 512;
const SETTLEMENT_HIT_RADIUS_PX = 10;
const SETTLEMENT_DOT_MIN_RADIUS_PX = 3;
const SETTLEMENT_DOT_RADIUS_PX = 5;
const SETTLEMENT_OUTLINE_WIDTH_PX = 1.5;
const SETTLEMENT_LABEL_FONT_PX = 12;
const SETTLEMENT_LABEL_OFFSET_PX = 3;
const BACKGROUND_COLOR = "#070a10";
const SETTLEMENT_COLOR = "#f0a500";
const SETTLEMENT_OUTLINE_COLOR = "#041012";
const LABEL_COLOR = "#e7eefc";
const GRID_LINE_STYLE = "rgba(255,255,255,0.18)";
const FULL_CIRCLE_RADIANS = Math.PI * 2;

export type Map2DMeta = {
  bbox?: Bbox;
  settlements?: Array<Settlement>;
  tileSize?: number;
  sampleWidth?: number;
  sampleHeight?: number;
};

export type MapFlags = {
  showSettlements?: boolean;
  showGrid?: boolean;
  opacity?: number;
};

type PointerTrack = { x: number; y: number };

export class Map2D {
  onProbe: ((point: ProbePoint | null) => void) | null = null;
  onHoverSettlement:
    | ((settlement: Settlement | null, sx: number, sy: number) => void)
    | null = null;

  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly pointers = new Map<number, PointerTrack>();
  private readonly boundResize: () => void;
  private readonly onPointerDown: (event: PointerEvent) => void;
  private readonly onPointerMove: (event: PointerEvent) => void;
  private readonly onPointerUp: () => void;
  private readonly onPointerCancel: (event: PointerEvent) => void;
  private readonly onWheel: (event: WheelEvent) => void;
  private readonly onKeyDown: (event: KeyboardEvent) => void;
  private image: HTMLImageElement | null = null;
  private settlements: Array<Settlement> = [];
  private bbox: Bbox = { west: -180, south: -90, east: 180, north: 90 };
  private showSettlements = true;
  private showGrid = false;
  private tileSize = DEFAULT_TILE_SIZE;
  private sampleWidth = 1;
  private sampleHeight = 1;
  private opacity = 1;
  private scale = 1;
  private tx = 0;
  private ty = 0;
  // Two active pointers at once switch the gesture from pan to pinch-zoom.
  private pinch: { dist: number } | null = null;
  private dragging = false;
  private lastX = 0;
  private lastY = 0;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const ctx = canvas.getContext("2d");
    if (ctx === null) {
      throw new Error("Map2D: canvas 2d context unavailable");
    }
    this.ctx = ctx;
    this.boundResize = () => this.resize();
    this.onPointerDown = (event) => this.pointerDown(event);
    this.onPointerMove = (event) => this.pointerMove(event);
    this.onPointerUp = () => this.pointerUp();
    this.onPointerCancel = (event) => this.endPointer(event.pointerId);
    this.onWheel = (event) => this.wheel(event);
    this.onKeyDown = (event) => this.keyDown(event);
    globalThis.addEventListener("resize", this.boundResize);
    canvas.addEventListener("pointerdown", this.onPointerDown);
    canvas.addEventListener("pointermove", this.onPointerMove);
    globalThis.addEventListener("pointerup", this.onPointerUp);
    canvas.addEventListener("pointercancel", this.onPointerCancel);
    canvas.addEventListener("wheel", this.onWheel, { passive: false });
    canvas.addEventListener("keydown", this.onKeyDown);
  }

  dispose(): void {
    globalThis.removeEventListener("resize", this.boundResize);
    this.canvas.removeEventListener("pointerdown", this.onPointerDown);
    this.canvas.removeEventListener("pointermove", this.onPointerMove);
    globalThis.removeEventListener("pointerup", this.onPointerUp);
    this.canvas.removeEventListener("pointercancel", this.onPointerCancel);
    this.canvas.removeEventListener("wheel", this.onWheel);
    this.canvas.removeEventListener("keydown", this.onKeyDown);
  }

  resize(): void {
    const parent = this.canvas.parentElement;
    if (parent === null) {
      return;
    }
    const dpr = Math.min(globalThis.devicePixelRatio, MAX_DEVICE_PIXEL_RATIO);
    const width = parent.clientWidth;
    const height = parent.clientHeight;
    this.canvas.width = Math.max(1, Math.floor(width * dpr));
    this.canvas.height = Math.max(1, Math.floor(height * dpr));
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  setImage(image: HTMLImageElement, meta: Map2DMeta): void {
    this.image = image;
    if (meta.bbox !== undefined) {
      this.bbox = meta.bbox;
    }
    if (meta.settlements !== undefined) {
      this.settlements = meta.settlements;
    }
    if (meta.tileSize !== undefined && meta.tileSize > 0) {
      this.tileSize = meta.tileSize;
    }
    if (meta.sampleWidth !== undefined && meta.sampleWidth > 0) {
      this.sampleWidth = meta.sampleWidth;
    }
    if (meta.sampleHeight !== undefined && meta.sampleHeight > 0) {
      this.sampleHeight = meta.sampleHeight;
    }
    this.fit();
  }

  setLayerFlags(flags: MapFlags): void {
    if (flags.showSettlements !== undefined) {
      this.showSettlements = flags.showSettlements;
    }
    if (flags.showGrid !== undefined) {
      this.showGrid = flags.showGrid;
    }
    if (flags.opacity !== undefined) {
      this.opacity = flags.opacity;
    }
    this.draw();
  }

  fit(): void {
    const parent = this.canvas.parentElement;
    if (this.image === null || parent === null) {
      return;
    }
    this.resize();
    const sx = (parent.clientWidth - FIT_PADDING_PX) / this.image.naturalWidth;
    const sy = (parent.clientHeight - FIT_PADDING_PX) / this.image.naturalHeight;
    this.scale = Math.min(sx, sy, MAX_FIT_SCALE);
    this.tx = (parent.clientWidth - this.image.naturalWidth * this.scale) / 2;
    this.ty = (parent.clientHeight - this.image.naturalHeight * this.scale) / 2;
    this.draw();
  }

  draw(): void {
    const parent = this.canvas.parentElement;
    if (parent === null) {
      return;
    }
    this.clearWithBackground(parent.clientWidth, parent.clientHeight);
    if (this.image === null) {
      return;
    }
    this.ctx.save();
    this.ctx.translate(this.tx, this.ty);
    this.ctx.scale(this.scale, this.scale);
    this.ctx.globalAlpha = this.opacity;
    this.ctx.imageSmoothingEnabled = this.scale < SMOOTH_SCALE_MAX;
    this.ctx.drawImage(this.image, 0, 0);
    this.ctx.globalAlpha = 1;
    if (this.showGrid && this.tileSize > 0) {
      this.drawGrid(this.image);
    }
    if (this.showSettlements) {
      this.drawSettlements(this.image);
    }
    this.ctx.restore();
  }

  private clearWithBackground(width: number, height: number): void {
    this.ctx.clearRect(0, 0, width, height);
    this.ctx.fillStyle = BACKGROUND_COLOR;
    this.ctx.fillRect(0, 0, width, height);
  }

  private drawGrid(image: HTMLImageElement): void {
    const viewWidth = image.naturalWidth;
    const viewHeight = image.naturalHeight;
    const scaleX = viewWidth / this.sampleWidth;
    const scaleZ = viewHeight / this.sampleHeight;
    const stepX = this.tileSize * scaleX;
    const stepZ = this.tileSize * scaleZ;
    this.ctx.strokeStyle = GRID_LINE_STYLE;
    this.ctx.lineWidth = 1 / this.scale;
    this.ctx.beginPath();
    for (let x = 0; x <= viewWidth; x += stepX) {
      this.ctx.moveTo(x, 0);
      this.ctx.lineTo(x, viewHeight);
    }
    for (let z = 0; z <= viewHeight; z += stepZ) {
      this.ctx.moveTo(0, z);
      this.ctx.lineTo(viewWidth, z);
    }
    this.ctx.stroke();
  }

  private drawSettlements(image: HTMLImageElement): void {
    for (const settlement of this.settlements) {
      const point = this.lonLatToImage(settlement.lon, settlement.lat, image);
      if (point !== null) {
        this.drawSettlementMarker(settlement, point);
      }
    }
  }

  private drawSettlementMarker(settlement: Settlement, point: { x: number; y: number }): void {
    const radius = Math.max(SETTLEMENT_DOT_MIN_RADIUS_PX, SETTLEMENT_DOT_RADIUS_PX / this.scale);
    this.ctx.beginPath();
    this.ctx.fillStyle = SETTLEMENT_COLOR;
    this.ctx.strokeStyle = SETTLEMENT_OUTLINE_COLOR;
    this.ctx.lineWidth = SETTLEMENT_OUTLINE_WIDTH_PX / this.scale;
    this.ctx.arc(point.x, point.y, radius, 0, FULL_CIRCLE_RADIANS);
    this.ctx.fill();
    this.ctx.stroke();
    if (this.scale > SETTLEMENT_LABEL_MIN_SCALE) {
      this.ctx.fillStyle = LABEL_COLOR;
      this.ctx.font = `${SETTLEMENT_LABEL_FONT_PX / this.scale}px sans-serif`;
      this.ctx.fillText(
        settlement.name,
        point.x + radius + 2,
        point.y + SETTLEMENT_LABEL_OFFSET_PX / this.scale
      );
    }
  }

  private lonLatToImage(
    lon: number,
    lat: number,
    image: HTMLImageElement
  ): { x: number; y: number } | null {
    const { west, south, east, north } = this.bbox;
    if (east <= west || north <= south) {
      return null;
    }
    const u = (lon - west) / (east - west);
    const v = (north - lat) / (north - south);
    return { x: u * image.naturalWidth, y: v * image.naturalHeight };
  }

  private screenToImage(sx: number, sy: number): { ix: number; iy: number } {
    return { ix: (sx - this.tx) / this.scale, iy: (sy - this.ty) / this.scale };
  }

  private pointerDown(event: PointerEvent): void {
    this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (this.pointers.size === 2) {
      // Second finger: switch from pan to pinch-zoom around the pair.
      const [first, second] = Array.from(this.pointers.values());
      if (first !== undefined && second !== undefined) {
        this.pinch = { dist: Math.hypot(first.x - second.x, first.y - second.y) };
        this.dragging = false;
        this.canvas.classList.remove("dragging");
      }
      return;
    }
    if (this.pointers.size > 2) {
      return;
    }
    this.dragging = true;
    this.lastX = event.clientX;
    this.lastY = event.clientY;
    this.canvas.classList.add("dragging");
    this.canvas.setPointerCapture?.(event.pointerId);
  }

  private pointerUp(): void {
    this.dragging = false;
    this.canvas.classList.remove("dragging");
  }

  private endPointer(pointerId: number): void {
    this.pointers.delete(pointerId);
    this.pinch = null;
    // One finger left after a pinch: resume panning from its position.
    const [rest] = Array.from(this.pointers.values());
    if (rest !== undefined) {
      this.dragging = true;
      this.lastX = rest.x;
      this.lastY = rest.y;
      this.canvas.classList.add("dragging");
      return;
    }
    this.pointerUp();
  }

  // Pinch-zoom step: scale around the current midpoint of the two pointers.
  private pinchMove(): void {
    const [first, second] = Array.from(this.pointers.values());
    if (first === undefined || second === undefined || this.pinch === null) {
      return;
    }
    const dist = Math.hypot(first.x - second.x, first.y - second.y);
    if (dist > 0 && this.pinch.dist > 0) {
      const rect = this.canvas.getBoundingClientRect();
      this.zoomAt(
        (first.x + second.x) / 2 - rect.left,
        (first.y + second.y) / 2 - rect.top,
        dist / this.pinch.dist
      );
      this.draw();
    }
    this.pinch = { dist };
  }

  private pointerMove(event: PointerEvent): void {
    if (this.pointers.has(event.pointerId)) {
      this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    }
    if (this.pinch !== null && this.pointers.size >= 2) {
      this.pinchMove();
      return;
    }

    const rect = this.canvas.getBoundingClientRect();
    const sx = event.clientX - rect.left;
    const sy = event.clientY - rect.top;

    if (this.dragging) {
      this.tx += event.clientX - this.lastX;
      this.ty += event.clientY - this.lastY;
      this.lastX = event.clientX;
      this.lastY = event.clientY;
      this.draw();
    }
    if (this.image === null) {
      return;
    }
    const { ix, iy } = this.screenToImage(sx, sy);
    const inside =
      ix >= 0 && iy >= 0 && ix <= this.image.naturalWidth && iy <= this.image.naturalHeight;
    if (!inside) {
      this.emitProbe(null);
      this.emitHover(null, sx, sy);
      return;
    }
    this.emitProbe(this.probeAt(ix, iy, this.image));
    this.emitHover(this.settlementHit(ix, iy), sx, sy);
  }

  private probeAt(ix: number, iy: number, image: HTMLImageElement): ProbePoint {
    const { west, south, east, north } = this.bbox;
    const u = ix / image.naturalWidth;
    const v = iy / image.naturalHeight;
    return {
      lon: west + u * (east - west),
      lat: north - v * (north - south),
      u,
      v,
      ix,
      iy,
    };
  }

  private settlementHit(ix: number, iy: number): Settlement | null {
    if (!this.showSettlements || this.image === null) {
      return null;
    }
    const threshold = SETTLEMENT_HIT_RADIUS_PX / this.scale;
    for (const settlement of this.settlements) {
      const point = this.lonLatToImage(settlement.lon, settlement.lat, this.image);
      if (point !== null && Math.hypot(point.x - ix, point.y - iy) < threshold) {
        return settlement;
      }
    }
    return null;
  }

  private emitProbe(point: ProbePoint | null): void {
    if (this.onProbe !== null) {
      this.onProbe(point);
    }
  }

  private emitHover(settlement: Settlement | null, sx: number, sy: number): void {
    if (this.onHoverSettlement !== null) {
      this.onHoverSettlement(settlement, sx, sy);
    }
  }

  private wheel(event: WheelEvent): void {
    event.preventDefault();
    const rect = this.canvas.getBoundingClientRect();
    this.zoomAt(
      event.clientX - rect.left,
      event.clientY - rect.top,
      event.deltaY < 0 ? ZOOM_IN_STEP : ZOOM_OUT_STEP
    );
    this.draw();
  }

  // Scale around a screen point, keeping that point anchored. Shared by the
  // wheel and the keyboard zoom so both behave identically.
  private zoomAt(sx: number, sy: number, factor: number): void {
    const nextScale = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, this.scale * factor));
    const ix = (sx - this.tx) / this.scale;
    const iy = (sy - this.ty) / this.scale;
    this.scale = nextScale;
    this.tx = sx - ix * this.scale;
    this.ty = sy - iy * this.scale;
  }

  // Keyboard pan/zoom for non-pointer users (the canvas is focusable in
  // index.html).
  private keyDown(event: KeyboardEvent): void {
    const parent = this.canvas.parentElement;
    if (this.image === null || parent === null) {
      return;
    }
    const step = event.shiftKey ? PAN_STEP_LARGE_PX : PAN_STEP_PX;
    const centerX = parent.clientWidth / 2;
    const centerY = parent.clientHeight / 2;
    switch (event.key) {
      case "ArrowLeft":
        this.tx += step;
        break;
      case "ArrowRight":
        this.tx -= step;
        break;
      case "ArrowUp":
        this.ty += step;
        break;
      case "ArrowDown":
        this.ty -= step;
        break;
      case "+":
      case "=":
        this.zoomAt(centerX, centerY, KEY_ZOOM_IN_STEP);
        break;
      case "-":
      case "_":
        this.zoomAt(centerX, centerY, KEY_ZOOM_OUT_STEP);
        break;
      case "Home":
      case "0":
        this.fit();
        event.preventDefault();
        return;
      default:
        return;
    }
    event.preventDefault();
    this.draw();
  }
}
