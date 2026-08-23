/**
 * Pan/zoom 2D map canvas with layer image + settlement markers.
 */

export class Map2D {
  /**
   * @param {HTMLCanvasElement} canvas
   */
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.image = null;
    this.settlements = [];
    this.bbox = { west: -180, south: -90, east: 180, north: 90 };
    this.showSettlements = true;
    this.showGrid = false;
    this.tileSize = 512;
    this.sampleWidth = 1;
    this.sampleHeight = 1;
    this.opacity = 1;

    this.scale = 1;
    this.tx = 0;
    this.ty = 0;
    this.dragging = false;
    this.lastX = 0;
    this.lastY = 0;
    // active pointers by id; two down at once means a pinch-zoom gesture
    this.pointers = new Map();
    this.pinch = null;

    this.onProbe = null;
    this.onHoverSettlement = null;

    this._boundResize = () => this.resize();
    this._onPointerDown = (e) => this._pointerDown(e);
    this._onPointerMove = (e) => this._pointerMove(e);
    this._onPointerUp = (e) => this._endPointer(e.pointerId);
    this._onPointerCancel = (e) => this._endPointer(e.pointerId);
    this._onWheel = (e) => this._wheel(e);
    this._onKeyDown = (e) => this._keydown(e);

    globalThis.addEventListener("resize", this._boundResize);
    canvas.addEventListener("pointerdown", this._onPointerDown);
    canvas.addEventListener("pointermove", this._onPointerMove);
    globalThis.addEventListener("pointerup", this._onPointerUp);
    canvas.addEventListener("pointercancel", this._onPointerCancel);
    canvas.addEventListener("wheel", this._onWheel, { passive: false });
    canvas.addEventListener("keydown", this._onKeyDown);
  }

  dispose() {
    globalThis.removeEventListener("resize", this._boundResize);
    this.canvas.removeEventListener("pointerdown", this._onPointerDown);
    this.canvas.removeEventListener("pointermove", this._onPointerMove);
    globalThis.removeEventListener("pointerup", this._onPointerUp);
    this.canvas.removeEventListener("pointercancel", this._onPointerCancel);
    this.canvas.removeEventListener("wheel", this._onWheel);
    this.canvas.removeEventListener("keydown", this._onKeyDown);
  }

  resize() {
    const parent = this.canvas.parentElement;
    const rawDpr = globalThis.devicePixelRatio;
    const dpr = Math.min(rawDpr === undefined ? 1 : rawDpr, 2);
    const w = parent.clientWidth;
    const h = parent.clientHeight;
    this.canvas.width = Math.max(1, Math.floor(w * dpr));
    this.canvas.height = Math.max(1, Math.floor(h * dpr));
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  /**
   * @param {HTMLImageElement} img
   * @param {object} meta
   */
  setImage(img, meta = {}) {
    this.image = img;
    if (meta.bbox) {
      this.bbox = meta.bbox;
    }
    if (meta.settlements) {
      this.settlements = meta.settlements;
    }
    if (meta.tileSize) {
      this.tileSize = meta.tileSize;
    }
    if (meta.sampleWidth) {
      this.sampleWidth = meta.sampleWidth;
    }
    if (meta.sampleHeight) {
      this.sampleHeight = meta.sampleHeight;
    }
    this.fit();
  }

  fit() {
    if (!this.image) {
      return;
    }
    this.resize();
    const pw = this.canvas.parentElement.clientWidth;
    const ph = this.canvas.parentElement.clientHeight;
    const pad = 40;
    const sx = (pw - pad) / this.image.naturalWidth;
    const sy = (ph - pad) / this.image.naturalHeight;
    this.scale = Math.min(sx, sy, 4);
    this.tx = (pw - this.image.naturalWidth * this.scale) / 2;
    this.ty = (ph - this.image.naturalHeight * this.scale) / 2;
    this.draw();
  }

  setLayerFlags({ showSettlements, showGrid, opacity }) {
    if (showSettlements !== undefined) {
      this.showSettlements = showSettlements;
    }
    if (showGrid !== undefined) {
      this.showGrid = showGrid;
    }
    if (opacity !== undefined) {
      this.opacity = opacity;
    }
    this.draw();
  }

  draw() {
    const { ctx } = this;
    const parent = this.canvas.parentElement;
    ctx.clearRect(0, 0, parent.clientWidth, parent.clientHeight);

    // subtle grid bg
    ctx.fillStyle = "#070a10";
    ctx.fillRect(0, 0, parent.clientWidth, parent.clientHeight);

    if (!this.image) {
      return;
    }

    ctx.save();
    ctx.translate(this.tx, this.ty);
    ctx.scale(this.scale, this.scale);
    ctx.globalAlpha = this.opacity;
    ctx.imageSmoothingEnabled = this.scale < 3;
    ctx.drawImage(this.image, 0, 0);
    ctx.globalAlpha = 1;

    if (this.showGrid && this.tileSize > 0) {
      const vw = this.image.naturalWidth;
      const vh = this.image.naturalHeight;
      const scaleX = vw / Math.max(1, this.sampleWidth);
      const scaleZ = vh / Math.max(1, this.sampleHeight);
      const stepX = this.tileSize * scaleX;
      const stepZ = this.tileSize * scaleZ;
      ctx.strokeStyle = "rgba(255,255,255,0.18)";
      ctx.lineWidth = 1 / this.scale;
      ctx.beginPath();
      for (let x = 0; x <= vw; x += stepX) {
        ctx.moveTo(x, 0);
        ctx.lineTo(x, vh);
      }
      for (let y = 0; y <= vh; y += stepZ) {
        ctx.moveTo(0, y);
        ctx.lineTo(vw, y);
      }
      ctx.stroke();
    }

    if (this.showSettlements) {
      for (const s of this.settlements) {
        const p = this.lonLatToImage(s.lon, s.lat);
        if (!p) {
          continue;
        }
        const r = Math.max(3, 5 / this.scale);
        ctx.beginPath();
        ctx.fillStyle = "#f0a500";
        ctx.strokeStyle = "#041012";
        ctx.lineWidth = 1.5 / this.scale;
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        if (this.scale > 0.6) {
          const { name } = s;
          ctx.fillStyle = "#e7eefc";
          ctx.font = `${12 / this.scale}px sans-serif`;
          ctx.fillText(name === undefined || name === null ? "?" : name, p.x + r + 2, p.y + 3 / this.scale);
        }
      }
    }
    ctx.restore();
  }

  lonLatToImage(lon, lat) {
    const { west, south, east, north } = this.bbox;
    if (east <= west || north <= south) {
      return null;
    }
    const u = (lon - west) / (east - west);
    const v = (north - lat) / (north - south);
    if (!this.image) {
      return null;
    }
    return {
      x: u * this.image.naturalWidth,
      y: v * this.image.naturalHeight,
    };
  }

  imageToLonLat(ix, iy) {
    const { west, south, east, north } = this.bbox;
    if (!this.image) {
      return null;
    }
    const u = ix / this.image.naturalWidth;
    const v = iy / this.image.naturalHeight;
    return {
      lon: west + u * (east - west),
      lat: north - v * (north - south),
      u,
      v,
    };
  }

  screenToImage(sx, sy) {
    const ix = (sx - this.tx) / this.scale;
    const iy = (sy - this.ty) / this.scale;
    return { ix, iy };
  }

  _pointerDown(e) {
    this.dragging = true;
    this.lastX = e.clientX;
    this.lastY = e.clientY;
    this.canvas.classList.add("dragging");
    this.canvas.setPointerCapture?.(e.pointerId);
  }

  _pointerUp() {
    this.dragging = false;
    this.canvas.classList.remove("dragging");
  }

  _pointerMove(e) {
    const rect = this.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (this.dragging) {
      this.tx += e.clientX - this.lastX;
      this.ty += e.clientY - this.lastY;
      this.lastX = e.clientX;
      this.lastY = e.clientY;
      this.draw();
    }

    if (!this.image) {
      return;
    }
    const { ix, iy } = this.screenToImage(sx, sy);
    if (ix < 0 || iy < 0 || ix > this.image.naturalWidth || iy > this.image.naturalHeight) {
      if (this.onProbe) {
        this.onProbe(null);
      }
      if (this.onHoverSettlement) {
        this.onHoverSettlement(null, sx, sy);
      }
      return;
    }
    const ll = this.imageToLonLat(ix, iy);
    if (this.onProbe) {
      this.onProbe({ ...ll, ix, iy, sx, sy });
    }

    let hit = null;
    if (this.showSettlements) {
      const thresh = 10 / this.scale;
      for (const s of this.settlements) {
        const p = this.lonLatToImage(s.lon, s.lat);
        if (!p) {
          continue;
        }
        if (Math.hypot(p.x - ix, p.y - iy) < thresh) {
          hit = s;
          break;
        }
      }
    }
    if (this.onHoverSettlement) {
      this.onHoverSettlement(hit, sx, sy);
    }
  }

  _wheel(e) {
    e.preventDefault();
    const rect = this.canvas.getBoundingClientRect();
    this.zoomAt(e.clientX - rect.left, e.clientY - rect.top, e.deltaY < 0 ? 1.12 : 1 / 1.12);
    this.draw();
  }

  // Scale around a screen point, keeping that point anchored. Shared by the
  // wheel and the keyboard zoom so both behave identically.
  zoomAt(sx, sy, factor) {
    const newScale = Math.min(32, Math.max(0.05, this.scale * factor));
    const ix = (sx - this.tx) / this.scale;
    const iy = (sy - this.ty) / this.scale;
    this.scale = newScale;
    this.tx = sx - ix * this.scale;
    this.ty = sy - iy * this.scale;
  }

  // Keyboard pan/zoom for non-pointer users (canvas is focusable in index.html).
  _keydown(e) {
    if (!this.image) {
      return;
    }
    const parent = this.canvas.parentElement;
    if (!parent) {
      return;
    }
    const step = e.shiftKey ? 160 : 60;
    switch (e.key) {
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
        this.zoomAt(parent.clientWidth / 2, parent.clientHeight / 2, 1.25);
        break;
      case "-":
      case "_":
        this.zoomAt(parent.clientWidth / 2, parent.clientHeight / 2, 0.8);
        break;
      case "Home":
      case "0":
        this.fit();
        e.preventDefault();
        return;
      default:
        return;
    }
    e.preventDefault();
    this.draw();
  }
}
