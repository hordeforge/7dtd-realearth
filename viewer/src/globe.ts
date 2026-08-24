// Three.js globe textured with the active layer image. Region packs are
// composited onto a full-earth equirectangular canvas so the sphere shows the
// whole world with the exported region highlighted; settlements are placed by
// lon/lat. three.js is resolved at runtime through the page importmap, so the
// CDN fetch only happens when Globe mode is first used.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { Bbox, Settlement } from "./types.js";

const MAX_DEVICE_PIXEL_RATIO = 2;
const FIELD_OF_VIEW_DEGREES = 45;
const NEAR_PLANE = 0.1;
const FAR_PLANE = 100;
const CAMERA_HEIGHT = 0.4;
const CAMERA_DISTANCE = 2.6;
const CONTROLS_MIN_DISTANCE = 1.3;
const CONTROLS_MAX_DISTANCE = 6;
const AMBIENT_COLOR = 0x88_99_BB;
const AMBIENT_INTENSITY = 0.55;
const KEY_LIGHT_COLOR = 0xFF_FF_FF;
const KEY_LIGHT_INTENSITY = 1.1;
const KEY_LIGHT_POSITION_X = 5;
const KEY_LIGHT_POSITION_Y = 3;
const KEY_LIGHT_POSITION_Z = 2;
const STAR_COUNT = 1500;
const VECTOR_AXES = 3;
const CENTERED_BIAS = 0.5;
const STARFIELD_EXTENT = 40;
const STAR_COLOR = 0xFF_FF_FF;
const STAR_SIZE = 0.02;
const STAR_OPACITY = 0.7;
const GLOBE_SEGMENTS_WIDE = 96;
const GLOBE_SEGMENTS_HIGH = 64;
const GLOBE_ROUGHNESS = 0.85;
const GLOBE_METALNESS = 0.05;
const AXIAL_TILT_DEGREES = 23.4;
const AXIAL_TILT_FACTOR = 0.15;
const SPIN_RADIANS_PER_FRAME = 0.0008;
const ATMOSPHERE_RADIUS = 1.03;
const ATMOSPHERE_SEGMENTS_WIDE = 64;
const ATMOSPHERE_SEGMENTS_HIGH = 48;
const ATMOSPHERE_COLOR = 0x3D_D6_C6;
const ATMOSPHERE_OPACITY = 0.07;
const MARKER_RADIUS = 0.012;
const MARKER_SEGMENTS = 10;
const MARKER_COLOR = 0xF0_A5_00;
const MARKER_ALTITUDE = 1.02;
const EARTH_TEXTURE_WIDTH = 2048;
const EARTH_TEXTURE_HEIGHT = 1024;
const OCEAN_COLOR = "#0a2744";
const GRATICULE_LINE_STYLE = "rgba(255,255,255,0.04)";
const MERIDIAN_GRID_LINES = 36;
const PARALLEL_GRID_LINES = 18;
const HIGHLIGHT_LINE_STYLE = "rgba(240,165,0,0.8)";
const HIGHLIGHT_LINE_WIDTH = 2;
// Region spans at least this wide already cover the globe; paste them as-is.
const FULL_EARTH_SPAN_DEGREES = 350;
const HALF_CIRCLE_DEGREES = 180;
const QUARTER_CIRCLE_DEGREES = 90;
const FULL_CIRCLE_DEGREES = 360;

type MarkerMesh = THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>;

function lonToEarthX(lon: number): number {
  return ((lon + HALF_CIRCLE_DEGREES) / FULL_CIRCLE_DEGREES) * EARTH_TEXTURE_WIDTH;
}

function latToEarthY(lat: number): number {
  return ((QUARTER_CIRCLE_DEGREES - lat) / HALF_CIRCLE_DEGREES) * EARTH_TEXTURE_HEIGHT;
}

function drawGraticule(ctx: CanvasRenderingContext2D): void {
  ctx.strokeStyle = GRATICULE_LINE_STYLE;
  for (let i = 0; i <= MERIDIAN_GRID_LINES; i += 1) {
    const x = (i / MERIDIAN_GRID_LINES) * EARTH_TEXTURE_WIDTH;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, EARTH_TEXTURE_HEIGHT);
    ctx.stroke();
  }
  for (let i = 0; i <= PARALLEL_GRID_LINES; i += 1) {
    const y = (i / PARALLEL_GRID_LINES) * EARTH_TEXTURE_HEIGHT;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(EARTH_TEXTURE_WIDTH, y);
    ctx.stroke();
  }
}

// Paste a region pack image onto a full-earth canvas with a highlight box.
function regionOnEarth(image: HTMLImageElement, bbox: Bbox): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = EARTH_TEXTURE_WIDTH;
  canvas.height = EARTH_TEXTURE_HEIGHT;
  const ctx = canvas.getContext("2d");
  if (ctx === null) {
    throw new Error("GlobeView: earth canvas 2d context unavailable");
  }
  ctx.fillStyle = OCEAN_COLOR;
  ctx.fillRect(0, 0, EARTH_TEXTURE_WIDTH, EARTH_TEXTURE_HEIGHT);
  drawGraticule(ctx);
  const x0 = lonToEarthX(bbox.west);
  const x1 = lonToEarthX(bbox.east);
  const y0 = latToEarthY(bbox.north);
  const y1 = latToEarthY(bbox.south);
  ctx.drawImage(image, x0, y0, Math.max(1, x1 - x0), Math.max(1, y1 - y0));
  ctx.strokeStyle = HIGHLIGHT_LINE_STYLE;
  ctx.lineWidth = HIGHLIGHT_LINE_WIDTH;
  ctx.strokeRect(x0, y0, Math.max(1, x1 - x0), Math.max(1, y1 - y0));

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

// Equirectangular placement: three.js SphereGeometry UVs already match
// lon/lat, so a point on the sphere follows from the same two angles.
function lonLatToVec3(lon: number, lat: number, radius: number): THREE.Vector3 {
  const phi = ((QUARTER_CIRCLE_DEGREES - lat) * Math.PI) / HALF_CIRCLE_DEGREES;
  const theta = ((lon + HALF_CIRCLE_DEGREES) * Math.PI) / FULL_CIRCLE_DEGREES;
  const x = -radius * Math.sin(phi) * Math.cos(theta);
  const z = radius * Math.sin(phi) * Math.sin(theta);
  const y = radius * Math.cos(phi);
  return new THREE.Vector3(x, y, z);
}

export class GlobeView {
  private readonly host: HTMLElement;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(
    FIELD_OF_VIEW_DEGREES,
    1,
    NEAR_PLANE,
    FAR_PLANE
  );
  private readonly controls: OrbitControls;
  private readonly markers = new THREE.Group();
  private readonly markerMeshes: Array<MarkerMesh> = [];
  // Auto-rotation pauses for users who ask the OS to reduce motion.
  private readonly reduceMotion = globalThis.matchMedia("(prefers-reduced-motion: reduce)");
  private readonly onResize = () => this.resize();
  private globe: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial> | null = null;
  private atmosphere: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial> | null = null;
  private texture: THREE.Texture | null = null;
  private raf = 0;

  constructor(host: HTMLElement) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio, MAX_DEVICE_PIXEL_RATIO));
    this.host.append(this.renderer.domElement);

    this.camera.position.set(0, CAMERA_HEIGHT, CAMERA_DISTANCE);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.minDistance = CONTROLS_MIN_DISTANCE;
    this.controls.maxDistance = CONTROLS_MAX_DISTANCE;
    this.controls.enablePan = false;

    this.addLights();
    this.addStarfield();
    this.scene.add(this.markers);

    globalThis.addEventListener("resize", this.onResize);
    this.resize();
    this.loop();
  }

  dispose(): void {
    cancelAnimationFrame(this.raf);
    globalThis.removeEventListener("resize", this.onResize);
    this.controls.dispose();
    this.renderer.dispose();
    if (this.texture !== null) {
      this.texture.dispose();
    }
    this.host.replaceChildren();
  }

  resize(): void {
    const width = this.host.clientWidth;
    const height = this.host.clientHeight;
    this.camera.aspect = width / Math.max(1, height);
    this.renderer.setSize(width, height, false);
    this.camera.updateProjectionMatrix();
  }

  setTexture(
    image: HTMLImageElement,
    settlements: ReadonlyArray<Settlement> = [],
    bbox: Bbox | null = null
  ): void {
    if (this.texture !== null) {
      this.texture.dispose();
    }
    const texture = new THREE.Texture(image);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.needsUpdate = true;
    texture.wrapS = THREE.ClampToEdgeWrapping;
    texture.wrapT = THREE.ClampToEdgeWrapping;
    this.texture = texture;

    if (this.globe !== null) {
      this.scene.remove(this.globe);
      this.globe.geometry.dispose();
      this.globe.material.dispose();
    }
    // Equirectangular: three.js SphereGeometry UVs already match lon/lat.
    // Region packs are pasted onto a full-earth canvas instead.
    let mapTexture: THREE.Texture = texture;
    if (bbox !== null && bbox.east - bbox.west < FULL_EARTH_SPAN_DEGREES) {
      mapTexture = regionOnEarth(image, bbox);
    }
    const geometry = new THREE.SphereGeometry(1, GLOBE_SEGMENTS_WIDE, GLOBE_SEGMENTS_HIGH);
    const material = new THREE.MeshStandardMaterial({
      map: mapTexture,
      roughness: GLOBE_ROUGHNESS,
      metalness: GLOBE_METALNESS,
    });
    this.globe = new THREE.Mesh(geometry, material);
    // slight axial tilt for drama
    this.globe.rotation.z =
      ((AXIAL_TILT_DEGREES * Math.PI) / HALF_CIRCLE_DEGREES) * AXIAL_TILT_FACTOR;
    this.scene.add(this.globe);

    if (this.atmosphere !== null) {
      this.scene.remove(this.atmosphere);
      this.atmosphere.geometry.dispose();
      this.atmosphere.material.dispose();
    }
    this.atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(
        ATMOSPHERE_RADIUS,
        ATMOSPHERE_SEGMENTS_WIDE,
        ATMOSPHERE_SEGMENTS_HIGH
      ),
      new THREE.MeshBasicMaterial({
        color: ATMOSPHERE_COLOR,
        transparent: true,
        opacity: ATMOSPHERE_OPACITY,
        side: THREE.BackSide,
      })
    );
    this.scene.add(this.atmosphere);

    this.placeMarkers(settlements);
  }

  private addLights(): void {
    const ambient = new THREE.AmbientLight(AMBIENT_COLOR, AMBIENT_INTENSITY);
    const key = new THREE.DirectionalLight(KEY_LIGHT_COLOR, KEY_LIGHT_INTENSITY);
    key.position.set(KEY_LIGHT_POSITION_X, KEY_LIGHT_POSITION_Y, KEY_LIGHT_POSITION_Z);
    this.scene.add(ambient, key);
  }

  private addStarfield(): void {
    const stars = new THREE.BufferGeometry();
    const positions = new Float32Array(STAR_COUNT * VECTOR_AXES);
    for (let i = 0; i < positions.length; i += 1) {
      positions[i] = (Math.random() - CENTERED_BIAS) * STARFIELD_EXTENT;
    }
    stars.setAttribute("position", new THREE.BufferAttribute(positions, VECTOR_AXES));
    this.scene.add(
      new THREE.Points(
        stars,
        new THREE.PointsMaterial({
          color: STAR_COLOR,
          size: STAR_SIZE,
          transparent: true,
          opacity: STAR_OPACITY,
        })
      )
    );
  }

  private placeMarkers(settlements: ReadonlyArray<Settlement>): void {
    this.clearMarkers();
    const geometry = new THREE.SphereGeometry(MARKER_RADIUS, MARKER_SEGMENTS, MARKER_SEGMENTS);
    const material = new THREE.MeshBasicMaterial({ color: MARKER_COLOR });
    for (const settlement of settlements) {
      const marker = new THREE.Mesh(geometry, material);
      marker.position.copy(lonLatToVec3(settlement.lon, settlement.lat, MARKER_ALTITUDE));
      marker.userData = settlement;
      this.markers.add(marker);
      this.markerMeshes.push(marker);
    }
  }

  private clearMarkers(): void {
    for (const marker of this.markerMeshes) {
      marker.geometry.dispose();
      marker.material.dispose();
      this.markers.remove(marker);
    }
    this.markerMeshes.length = 0;
  }

  private loop(): void {
    this.raf = requestAnimationFrame(() => this.loop());
    // flat mode hides the host; skip all render work until it is shown again
    if (this.host.hidden) {
      return;
    }
    this.controls.update();
    if (this.globe !== null && !this.reduceMotion.matches) {
      this.globe.rotation.y += SPIN_RADIANS_PER_FRAME;
    }
    this.renderer.render(this.scene, this.camera);
  }
}
