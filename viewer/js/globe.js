/**
 * Simple Three.js globe textured with the current layer image.
 */

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export class GlobeView {
  /**
   * @param {HTMLElement} host
   */
  constructor(host) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    const rawDpr = globalThis.devicePixelRatio;
    this.renderer.setPixelRatio(Math.min(rawDpr === undefined ? 1 : rawDpr, 2));
    this.host.append(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    this.camera.position.set(0, 0.4, 2.6);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.minDistance = 1.3;
    this.controls.maxDistance = 6;
    this.controls.enablePan = false;

    const amb = new THREE.AmbientLight(0x88_99_BB, 0.55);
    const key = new THREE.DirectionalLight(0xFF_FF_FF, 1.1);
    key.position.set(5, 3, 2);
    this.scene.add(amb, key);

    // starfield
    const stars = new THREE.BufferGeometry();
    const starPos = new Float32Array(1500 * 3);
    for (let i = 0; i < starPos.length; i += 1) {
      starPos[i] = (Math.random() - 0.5) * 40;
    }
    stars.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
    this.scene.add(
      new THREE.Points(
        stars,
        new THREE.PointsMaterial({ color: 0xFF_FF_FF, size: 0.02, transparent: true, opacity: 0.7 })
      )
    );

    this.globe = null;
    this.markers = new THREE.Group();
    this.scene.add(this.markers);
    this.texture = null;
    this.raf = 0;
    // Auto-rotation pauses for users who ask the OS to reduce motion.
    this.reduceMotion =
      typeof globalThis.matchMedia === "function"
        ? globalThis.matchMedia("(prefers-reduced-motion: reduce)")
        : null;
    this._onResize = () => this.resize();
    globalThis.addEventListener("resize", this._onResize);
    this.resize();
    this._loop();
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    globalThis.removeEventListener("resize", this._onResize);
    this.controls.dispose();
    this.renderer.dispose();
    if (this.texture) {
      this.texture.dispose();
    }
    this.host.replaceChildren();
  }

  resize() {
    const width = this.host.clientWidth;
    const height = this.host.clientHeight;
    this.camera.aspect = width / Math.max(1, height);
    this.renderer.setSize(width, height, false);
    this.camera.updateProjectionMatrix();
  }

  /**
   * @param {HTMLImageElement} img
   * @param {Array} settlements
   * @param {object} bbox region only textures: map UV into full globe
   */
  setTexture(img, settlements = [], bbox = null) {
    if (this.texture) {
      this.texture.dispose();
    }
    this.texture = new THREE.Texture(img);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.texture.needsUpdate = true;
    this.texture.wrapS = THREE.ClampToEdgeWrapping;
    this.texture.wrapT = THREE.ClampToEdgeWrapping;

    if (this.globe) {
      this.scene.remove(this.globe);
      this.globe.geometry.dispose();
      this.globe.material.dispose();
    }

    const geo = new THREE.SphereGeometry(1, 96, 64);
    // Equirectangular: three.js SphereGeometry UVs already match lon/lat
    // For region packs, build a canvas full-earth with region pasted
    let mapTex = this.texture;
    if (
      bbox &&
      bbox.west !== undefined &&
      bbox.west !== null &&
      bbox.east !== undefined &&
      bbox.east !== null &&
      bbox.east - bbox.west < 350
    ) {
      mapTex = regionOnEarth(img, bbox);
    }

    const mat = new THREE.MeshStandardMaterial({
      map: mapTex,
      roughness: 0.85,
      metalness: 0.05,
    });
    this.globe = new THREE.Mesh(geo, mat);
    // slight axial tilt for drama
    this.globe.rotation.z = (23.4 * Math.PI) / 180 * 0.15;
    this.scene.add(this.globe);

    // atmosphere shell
    if (this.atmosphere) {
      this.scene.remove(this.atmosphere);
      this.atmosphere.geometry.dispose();
      this.atmosphere.material.dispose();
    }
    this.atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(1.03, 64, 48),
      new THREE.MeshBasicMaterial({
        color: 0x3D_D6_C6,
        transparent: true,
        opacity: 0.07,
        side: THREE.BackSide,
      })
    );
    this.scene.add(this.atmosphere);

    this._placeMarkers(settlements);
  }

  _placeMarkers(settlements) {
    while (this.markers.children.length > 0) {
      const c = this.markers.children.pop();
      c.geometry?.dispose?.();
      c.material?.dispose?.();
    }
    const geo = new THREE.SphereGeometry(0.012, 10, 10);
    const mat = new THREE.MeshBasicMaterial({ color: 0xF0_A5_00 });
    for (const s of settlements) {
      const m = new THREE.Mesh(geo, mat);
      m.position.copy(lonLatToVec3(s.lon, s.lat, 1.02));
      m.userData = s;
      this.markers.add(m);
    }
  }

  _loop() {
    this.raf = requestAnimationFrame(() => this._loop());
    // flat mode hides the host; skip all render work until it is shown again
    if (this.host.hidden) {
      return;
    }
    this.controls.update();
    if (this.globe && !(this.reduceMotion && this.reduceMotion.matches)) {
      this.globe.rotation.y += 0.0008;
    }
    this.renderer.render(this.scene, this.camera);
  }
}

/**
 * Paste a region pack image onto a full-earth canvas with a highlight box.
 */
function regionOnEarth(img, bbox) {
  const W = 2048;
  const H = 1024;
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const ctx = c.getContext("2d");
  // ocean base
  ctx.fillStyle = "#0a2744";
  ctx.fillRect(0, 0, W, H);
  // faint grid
  ctx.strokeStyle = "rgba(255,255,255,0.04)";
  for (let i = 0; i <= 36; i += 1) {
    const x = (i / 36) * W;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, H);
    ctx.stroke();
  }
  for (let i = 0; i <= 18; i += 1) {
    const y = (i / 18) * H;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }

  const x0 = ((bbox.west + 180) / 360) * W;
  const x1 = ((bbox.east + 180) / 360) * W;
  const y0 = ((90 - bbox.north) / 180) * H;
  const y1 = ((90 - bbox.south) / 180) * H;
  ctx.drawImage(img, x0, y0, Math.max(1, x1 - x0), Math.max(1, y1 - y0));
  // highlight box
  ctx.strokeStyle = "rgba(240,165,0,0.8)";
  ctx.lineWidth = 2;
  ctx.strokeRect(x0, y0, Math.max(1, x1 - x0), Math.max(1, y1 - y0));

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  return tex;
}

function lonLatToVec3(lon, lat, r = 1) {
  const phi = ((90 - lat) * Math.PI) / 180;
  const theta = ((lon + 180) * Math.PI) / 180;
  const x = -r * Math.sin(phi) * Math.cos(theta);
  const z = r * Math.sin(phi) * Math.sin(theta);
  const y = r * Math.cos(phi);
  return new THREE.Vector3(x, y, z);
}
