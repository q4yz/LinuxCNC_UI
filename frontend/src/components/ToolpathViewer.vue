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
//
// The Float32Array build + bounding-box pass runs in `toolpathWorker.ts`,
// not here. A large real-world G-code file can be tens of thousands
// of segments — building `positions`/`colors` and walking every
// point for the bounding box synchronously on `watch(segments)` would
// freeze the tab for the whole preview-open, the same main-thread
// stall class the live NGC viewer already had to be fixed for
// (fill-rate / main-thread saturation). The worker hands the
// finished buffers back as transferable objects
// (`postMessage(..., [positions.buffer, colors.buffer])`), a
// zero-copy handoff rather than a structured-clone of the whole
// array. `currentJobId` guards against a stale response landing after
// the operator has already clicked a different file to preview.
//
// `props.segments` is a Vue reactive Proxy (it flows down from a
// `ref<ParsedSegment[]>` in `FileManager.vue`) — `postMessage`'s own
// structured-clone step cannot clone a Proxy (`DataCloneError:
// [object Object] could not be cloned`, confirmed live). `toRaw()`
// strips that wrapper before the array ever reaches `postMessage`;
// nested segment objects were never independently proxied (Vue wraps
// nested access lazily through the outer proxy, it doesn't mutate the
// stored data), so this one unwrap is enough.

import { onBeforeUnmount, onMounted, ref, toRaw, watch } from "vue";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { ParsedSegment } from "../parsers/gcodeParser";
import { useRenderQuality } from "../composables/useRenderQuality";
import type { ToolpathWorkerBounds, ToolpathWorkerResponse } from "./toolpathWorker";

const props = defineProps<{
  segments: ParsedSegment[];
}>();

const containerEl = ref<HTMLDivElement | null>(null);
const isProcessing = ref(false);

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let controls: OrbitControls | null = null;
let toolpathMesh: THREE.LineSegments | null = null;
let resizeObserver: ResizeObserver | null = null;

let worker: Worker | null = null;
let currentJobId = 0;

// Render-on-demand, same pattern (and same reasoning) as
// ``NgcCoordinateSystemViewer.vue``: redraw only when the camera
// moved, the mesh was rebuilt, or the container resized — not every
// animation frame unconditionally.
let needsRender = true;
function requestRender(): void {
  needsRender = true;
}

const { rendererOptions, pixelRatioFor } = useRenderQuality();

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

  renderer = new THREE.WebGLRenderer({ ...rendererOptions(), alpha: false });
  renderer.setPixelRatio(pixelRatioFor(window.devicePixelRatio));
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.addEventListener("change", requestRender);

  resizeObserver = new ResizeObserver(() => {
    if (!container || !renderer || !camera) return;
    const w = Math.max(container.clientWidth, 1);
    const h = Math.max(container.clientHeight, 1);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    requestRender();
  });
  resizeObserver.observe(container);

  renderLoop();
}

function renderLoop(): void {
  if (!renderer || !scene || !camera || !controls) return;
  controls.update();
  if (needsRender) {
    needsRender = false;
    renderer.render(scene, camera);
  }
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

// Frame the toolpath's bounding box: camera looks from Z+ down to
// Z− (top-down, so X reads right and Y reads up like the slicer
// preview) with a slight tilt for depth perception. No base grid —
// the toolpath speaks for itself.
function fitToBounds(bounds: ToolpathWorkerBounds): void {
  if (!scene || !camera || !controls) return;

  const sizeX = bounds.maxX - bounds.minX;
  const sizeY = bounds.maxY - bounds.minY;
  const sizeZ = bounds.maxZ - bounds.minZ;

  const centerX = bounds.minX + sizeX / 2;
  const centerY = bounds.minY + sizeY / 2;
  const centerZ = bounds.minZ + sizeZ / 2;

  const span = Math.max(sizeX, sizeY, sizeZ, 10);
  const distance = span * 1.6;
  // Mostly along +Z (looking down at the XY plane) with a slight
  // tilt (~19°) so depth still reads.
  camera.position.set(
    centerX + distance * 0.18,
    centerY + distance * 0.28,
    centerZ + distance,
  );
  controls.target.set(centerX, centerY, centerZ);
  controls.update();
}

// Empty-segments framing: same "collapse to origin" fallback the
// synchronous version used, skipped entirely by the worker path
// below (no job is posted for an empty array) so it has to be
// handled here instead.
function frameOrigin(): void {
  if (!scene || !camera || !controls) return;
  const span = 10;
  const distance = span * 1.6;
  camera.position.set(distance * 0.18, distance * 0.28, distance);
  controls.target.set(0, 0, 0);
  controls.update();
}

function requestWorkerRender(): void {
  if (!worker || props.segments.length === 0) {
    clearToolpath();
    frameOrigin();
    requestRender();
    return;
  }

  currentJobId++;
  isProcessing.value = true;

  worker.postMessage({
    jobId: currentJobId,
    segments: toRaw(props.segments),
  });
}

function handleWorkerMessage(e: MessageEvent<ToolpathWorkerResponse>): void {
  const { jobId, positions, colors, bounds } = e.data;

  // Ignore stale responses if the operator changed the selected file
  // rapidly — only the most recently requested job may still land.
  if (jobId !== currentJobId) return;
  isProcessing.value = false;

  clearToolpath();

  if (positions && colors && bounds && scene) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

    const material = new THREE.LineBasicMaterial({ vertexColors: true });
    toolpathMesh = new THREE.LineSegments(geometry, material);
    scene.add(toolpathMesh);

    fitToBounds(bounds);
    requestRender();
  }
}

watch(() => props.segments, () => requestWorkerRender());

onMounted(() => {
  worker = new Worker(new URL("./toolpathWorker.ts", import.meta.url), { type: "module" });
  worker.onmessage = handleWorkerMessage;

  initScene();
  requestWorkerRender();
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
  clearToolpath();
  controls?.removeEventListener("change", requestRender);
  controls?.dispose();
  controls = null;
  renderer?.dispose();
  renderer = null;
  scene = null;
  camera = null;
  worker?.terminate();
  worker = null;
});
</script>

<template>
  <div class="relative h-full w-full">
    <div
      ref="containerEl"
      class="h-full w-full rounded-md border border-gray-700 bg-gray-950"
      data-test="toolpath-viewer"
    ></div>

    <div
        v-if="isProcessing"
        class="absolute inset-0 flex items-center justify-center bg-gray-950/60 backdrop-blur-[2px] transition-opacity"
        data-test="toolpath-viewer-processing"
    >
      <div class="flex flex-col items-center">
        <div class="mb-4 h-10 w-10 animate-spin rounded-full border-4 border-gray-600 border-t-blue-500"></div>
        <span class="text-sm font-medium text-gray-300">Processing toolpath…</span>
      </div>
    </div>
  </div>
</template>
