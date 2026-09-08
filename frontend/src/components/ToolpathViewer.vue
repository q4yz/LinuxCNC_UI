<script setup lang="ts">
// Jog-free 3D toolpath renderer — the rendering core extracted from
// `NgcCoordinateSystemViewer.vue` (same segment → Float32Array mesh
// build, same pending/cut color palette) so file previews can reuse
// the coordinate viewer's 3D view without dragging machine-store,
// telemetry or the viewer's window-level jog key bindings into a
// passive dialog. Camera frames the part top-down (Z+ → Z−, slight
// tilt); no base grid.
//
// Deliberately dependency-free: no Pinia stores, no key listeners,
// no network. Props in, pixels out.

import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { ParsedSegment } from "../parsers/gcodeParser";

const props = defineProps<{
  segments: ParsedSegment[];
}>();

// Same palette the coordinate viewer uses (pending = blue).
const COLOR_PENDING_R = 0x60 / 255;
const COLOR_PENDING_G = 0xa5 / 255;
const COLOR_PENDING_B = 0xfa / 255;

const containerEl = ref<HTMLDivElement | null>(null);

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let controls: OrbitControls | null = null;
let toolpathMesh: THREE.LineSegments | null = null;
let resizeObserver: ResizeObserver | null = null;

function initScene(): void {
  const container = containerEl.value;
  if (!container || renderer) return;

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0f19);

  camera = new THREE.PerspectiveCamera(
    50,
    Math.max(container.clientWidth, 1) / Math.max(container.clientHeight, 1),
    0.1,
    5000,
  );

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  resizeObserver = new ResizeObserver(() => {
    if (!container || !renderer || !camera) return;
    const w = Math.max(container.clientWidth, 1);
    const h = Math.max(container.clientHeight, 1);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  });
  resizeObserver.observe(container);

  renderLoop();
}

function renderLoop(): void {
  if (!renderer || !scene || !camera || !controls) return;
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(renderLoop);
}

// --- toolpath mesh ---------------------------------------------------------

function clearToolpath(): void {
  if (!scene || !toolpathMesh) return;
  scene.remove(toolpathMesh);
  toolpathMesh.geometry.dispose();
  (toolpathMesh.material as THREE.Material).dispose();
  toolpathMesh = null;
}

function buildMesh(segments: ParsedSegment[]): THREE.LineSegments | null {
  if (segments.length === 0) return null;
  // Same flat-array build the coordinate viewer uses (raw program
  // coordinates — a preview applies no runtime WCS/G92 offsets).
  const flat = new Float32Array(segments.length * 6);
  const colors = new Float32Array(segments.length * 6);
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const o = i * 6;
    flat[o] = seg.from[0];
    flat[o + 1] = seg.from[1];
    flat[o + 2] = seg.from[2];
    flat[o + 3] = seg.to[0];
    flat[o + 4] = seg.to[1];
    flat[o + 5] = seg.to[2];
    colors[o] = COLOR_PENDING_R;
    colors[o + 1] = COLOR_PENDING_G;
    colors[o + 2] = COLOR_PENDING_B;
    colors[o + 3] = COLOR_PENDING_R;
    colors[o + 4] = COLOR_PENDING_G;
    colors[o + 5] = COLOR_PENDING_B;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(flat, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const material = new THREE.LineBasicMaterial({ vertexColors: true });
  return new THREE.LineSegments(geometry, material);
}

// Frame the toolpath's bounding box: camera looks from Z+ down to
// Z− (top-down, so X reads right and Y reads up like the slicer
// preview) with a slight tilt for depth perception. No base grid —
// the toolpath speaks for itself.
function fitTo(segments: ParsedSegment[]): void {
  if (!scene || !camera || !controls) return;

  const box = new THREE.Box3();
  for (const seg of segments) {
    box.expandByPoint(new THREE.Vector3(...seg.from));
    box.expandByPoint(new THREE.Vector3(...seg.to));
  }
  if (box.isEmpty()) {
    box.expandByPoint(new THREE.Vector3(0, 0, 0));
  }
  const size = new THREE.Vector3();
  box.getSize(size);
  const center = new THREE.Vector3();
  box.getCenter(center);

  const span = Math.max(size.x, size.y, size.z, 10);
  const distance = span * 1.6;
  // Mostly along +Z (looking down at the XY plane) with a slight
  // tilt (~19°) so depth still reads.
  camera.position.set(
    center.x + distance * 0.18,
    center.y + distance * 0.28,
    center.z + distance,
  );
  controls.target.copy(center);
  controls.update();
}

function render(): void {
  if (!scene) return;
  clearToolpath();
  const mesh = buildMesh(props.segments);
  if (mesh) {
    scene.add(mesh);
    toolpathMesh = mesh;
  }
  fitTo(props.segments);
}

watch(() => props.segments, () => render());

onMounted(() => {
  initScene();
  render();
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
  clearToolpath();
  controls?.dispose();
  controls = null;
  renderer?.dispose();
  renderer = null;
  scene = null;
  camera = null;
});
</script>

<template>
  <div
    ref="containerEl"
    class="h-full w-full rounded-md border border-gray-700 bg-gray-950"
    data-test="toolpath-viewer"
  ></div>
</template>
