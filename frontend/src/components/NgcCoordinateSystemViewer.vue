<script setup>
// NgcCoordinateSystemViewer — Three.js toolpath viewer for the dashboard.
//
// Renders three things on top of the standard grid + axes + toolhead
// rig the original component shipped with:
//
//   1. A wireframe "limits box" in the X/Y plane drawn from the
//      machine limits declared in the active ``hardware.json``
//      (``axes[].steppers[].position_min`` / ``position_max``). The
//      box hides itself when the limits are missing so a freshly
//      compiled-but-not-yet-deployed configuration does not surprise
//      the operator with an empty rect.
//
//   2. The currently loaded G-code / NGC program's toolpath, fetched
//      from ``/api/v1/programs/content/{filename}`` whenever
//      ``useMachineStore().status.file`` changes. Performance is
//      intentionally not optimised yet — a single ``LineSegments``
//      is built synchronously per program load. G2 / G3 arcs are
//      linear-approximated (one chord per G-code word) until a
//      proper arc interpolator lands.
//
//   3. A small overlay showing the active limits and the move count
//      so the operator can sanity-check the box against the profile
//      without opening the JSON.
//
// The component used to be wired under the name ``GcodeViewer`` on
// the dashboard; the import in ``DashboardView.vue`` was pointing at
// a non-existent file so the panel silently failed to mount. The
// rename here + the import fix in ``DashboardView.vue`` re-enables
// the panel.

import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { useMachineStore } from '../stores/machine'
import { useMachineConfigStore } from '../modules/machineconfig/store'
import { ProgramFilesService } from '../../generated/api/services/ProgramFilesService'

const store = useMachineStore()
const machineconfigStore = useMachineConfigStore()

// Template ref for the container div
const container = ref(null)

// Three.js instances
let scene, camera, renderer, controls
let toolheadGroup, toolheadMesh
let limitsGroup
let toolpathLine
let animationFrameId
let resizeObserver

// Reactive UI state
const machineLimits = ref(null)
const toolpathMeta = ref({ filename: '', moves: 0 })

// Operator-facing toggles.
const props = defineProps({
  // Whether the rendered toolpath should be offset by the
  // interpreter's active work origin (``g5x_offset`` plus the
  // optional ``g92_offset`` additive origin). Default ``true`` —
  // most operators expect the toolpath to land where the cut
  // actually happens, not at the literal G-code coordinates.
  applyWorkingOffset: { type: Boolean, default: true },
})

// Formatting helper for the overlay — ``g5x_offset`` /
// ``g92_offset`` are 9-element per-axis arrays on the live
// stat. We surface the X/Y/Z trio the operator cares about.
const formatOffset = (axis) => {
  if (!Array.isArray(axis) || axis.length < 3) return '0,0,0'
  const fmt = (n) => (Number.isFinite(n) ? n.toFixed(2) : '0')
  return `${fmt(axis[0])},${fmt(axis[1])},${fmt(axis[2])}`
}

// Tracking helpers (non-reactive — the meshes themselves own Three state)
let lastLoadedFilename = ''

onMounted(async () => {
  initThreeJS()
  setupWatchers()
  animate()
  // Kick off the limits fetch after the scene is up so the box can
  // be added directly. The hardware.json fetch is awaited so the
  // first frame already shows the box when it exists.
  await loadMachineLimits()
  // If a program was already loaded (hot reload / dashboard re-mount
  // while the interpreter still has ``stat.file`` set), pull its
  // toolpath too.
  if (typeof store.status.file === 'string' && store.status.file.length > 0) {
    await loadProgramToolpath(store.status.file)
  }
})

onBeforeUnmount(() => {
  // 1. Stop animation loop
  cancelAnimationFrame(animationFrameId)

  // 2. Stop observing resizes
  if (resizeObserver && container.value) {
    resizeObserver.unobserve(container.value)
  }

  // 3. Clean up Three.js memory (geometries, materials, renderer)
  if (renderer) {
    renderer.dispose()
  }

  // Traverse scene to dispose of geometries and materials
  if (scene) {
    scene.traverse((object) => {
      if (!object.isMesh && !object.isLine && !object.isLineSegments) return

      if (object.geometry) {
        object.geometry.dispose()
      }

      if (object.material) {
        if (object.material.isMaterial) {
          cleanMaterial(object.material)
        } else {
          // an array of materials
          for (const material of object.material) cleanMaterial(material)
        }
      }
    })
  }

  // Clean up controls
  if (controls) {
    controls.dispose()
  }
})

const cleanMaterial = material => {
  material.dispose()
  // dispose textures
  for (const key of Object.keys(material)) {
    const value = material[key]
    if (value && typeof value === 'object' && 'minFilter' in value) {
      value.dispose()
    }
  }
}

const initThreeJS = () => {
  const width = container.value.clientWidth
  const height = container.value.clientHeight

  // --- Scene Setup ---
  scene = new THREE.Scene()
  scene.background = new THREE.Color('#1f2937') // Tailwind gray-800 to match UI

  // CRITICAL: Map Three.js Y-up to LinuxCNC Z-up
  // We rotate the entire main group so X/Y are flat and Z points up.
  const cncSpace = new THREE.Group()
  cncSpace.rotation.x = -Math.PI / 2 // Rotate -90 degrees on X
  scene.add(cncSpace)

  // --- Camera Setup ---
  camera = new THREE.PerspectiveCamera(45, width / height, 1, 10000)
  // Position camera nicely to view the Z-up coordinate system
  camera.position.set(200, 200, 200)
  camera.lookAt(0, 0, 0)

  // --- Renderer Setup ---
  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(width, height)
  renderer.setPixelRatio(window.devicePixelRatio)
  container.value.appendChild(renderer.domElement)

  // --- Controls ---
  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.05

  // --- Environment Helpers (Inside cncSpace) ---
  // The floor grid is built dynamically from the machine's active
  // limits in ``setMachineLimits`` once the hardware.json fetch
  // has resolved. A static 500 mm grid was misleading on
  // machines with smaller work envelopes (a 200 mm bed showed
  // 300 mm of empty grid outside the outline). The GridHelper
  // instance lives only as long as the limits that produced it.
  //
  // AxesHelper (Size: 100mm)
  // Red = X, Green = Y (Three's Y is our Z now), Blue = Z (Three's Z is our -Y now)
  const axesHelper = new THREE.AxesHelper(100)
  cncSpace.add(axesHelper)

  // --- Toolhead Mesh ---
  toolheadGroup = new THREE.Group()

  // Simple Cone to represent an endmill pointing down
  const geometry = new THREE.ConeGeometry(5, 20, 16)
  // Rotate the cone so the tip points along the negative Z-axis (-Z)
  geometry.rotateX(-Math.PI / 2)
  // Move geometry up along Z so the tip touches the origin (0,0,0)
  geometry.translate(0, 0, 10)

  const material = new THREE.MeshBasicMaterial({
    color: 0xef4444, // Tailwind red-500
    wireframe: false,
    transparent: true,
    opacity: 0.8
  })

  toolheadMesh = new THREE.Mesh(geometry, material)

  // Since we rotated cncSpace, the cone's "Up" (Y) is now our Z
  toolheadGroup.add(toolheadMesh)
  cncSpace.add(toolheadGroup)

  // Set initial position
  updateToolheadPosition()

  // --- Limits box group (children added/removed by loadMachineLimits) ---
  limitsGroup = new THREE.Group()
  cncSpace.add(limitsGroup)

  // --- Resize Handling ---
  resizeObserver = new ResizeObserver(entries => {
    for (let entry of entries) {
      const newWidth = entry.contentRect.width
      const newHeight = entry.contentRect.height
      renderer.setSize(newWidth, newHeight)
      camera.aspect = newWidth / newHeight
      camera.updateProjectionMatrix()
    }
  })
  resizeObserver.observe(container.value)
}

const updateToolheadPosition = () => {
  if (!toolheadGroup) return

  const [x, y, z] = store.status.position

  // Since toolheadGroup is INSIDE cncSpace (which is rotated -90 on X),
  // we can map X, Y, Z directly to Three's X, Y, Z!
  // The rotation handles the visual translation.
  toolheadGroup.position.set(x, y, z)

  // Alternatively, if you didn't rotate cncSpace, you would do:
  // toolheadMesh.position.set(x, z, -y)
}

const setupWatchers = () => {
  // Watch the reactive array deeply
  watch(() => store.status.position, () => {
    updateToolheadPosition()
  }, { deep: true })

  // Watch for program load / unload. ``status.file`` is the basename
  // of the interpreter's loaded program (empty string when nothing
  // is loaded). The watcher fires on every transition; the dedup
  // against ``lastLoadedFilename`` keeps the fetch + parse work to
  // one round-trip per real change.
  watch(() => store.status.file, async (newFile) => {
    if (typeof newFile === 'string' && newFile.length > 0) {
      await loadProgramToolpath(newFile)
      // Re-fetch limits too — any deploy that changes limits almost
      // always loads a new program, so the limits refresh piggybacks
      // on the same hook without needing a separate pub-sub channel.
      await loadMachineLimits()
    } else {
      clearToolpath()
    }
  })

  // Re-render the toolpath when the work origin shifts so the
  // rendered cut line tracks where the operator's G54 / G92
  // actually places it. The watcher is deep so a single array
  // mutation (e.g. ``set g5x_offset[0] = -47``) triggers a rebuild.
  watch(
    () => [
      store.status.g5x_offset && store.status.g5x_offset.slice(0, 3),
      store.status.g92_offset && store.status.g92_offset.slice(0, 3),
    ],
    async () => {
      if (lastLoadedFilename) {
        await loadProgramToolpath(lastLoadedFilename)
      }
    },
    { deep: true },
  )

  // Watch the machineconfig store's machine name as a deploy hint.
  // The ``machine-name`` endpoint reads from the active INI which
  // lives next to ``hardware.json`` — both flip on the same deploy.
  watch(() => machineconfigStore.activeListing?.machine_name, async (name) => {
    if (typeof name === 'string' && name.length > 0) {
      await loadMachineLimits()
    }
  })
}

// ---------------------------------------------------------------------- //
// Machine limits box                                                      //
// ---------------------------------------------------------------------- //
//
// Reads ``machine_config/active/hardware.json`` via the machineconfig
// module's existing read endpoint, derives ``xMin/xMax/yMin/yMax``
// from every stepper's ``position_min`` / ``position_max`` (taking
// the looser bound across multi-motor axes — e.g. ``[stepper_x]`` +
// ``[stepper_x1]``), and rebuilds the wireframe rectangle.

const loadMachineLimits = async () => {
  if (!scene) return

  try {
    const response = await machineconfigStore.readActiveFileContent('hardware.json')
    const text = typeof response === 'string' ? response : ''
    if (!text) {
      setMachineLimits(null)
      return
    }

    let payload
    try {
      payload = JSON.parse(text)
    } catch (parseErr) {
      console.warn('[NgcCoordinateSystemViewer] hardware.json parse failed', parseErr)
      setMachineLimits(null)
      return
    }

    const limits = _extractLimitsFromHardwareJson(payload)
    setMachineLimits(limits)
  } catch (err) {
    // Active file is unavailable (no deploy yet, or backend down) —
    // hide the box. Don't surface a toast: the dashboard already
    // shows "(no active configuration)" elsewhere.
    setMachineLimits(null)
  }
}

const _extractLimitsFromHardwareJson = (payload) => {
  if (!payload || typeof payload !== 'object') return null

  const steppers = Array.isArray(payload.steppers) ? payload.steppers : []
  if (!steppers.length) return null

  // Map axis letter -> {min, max}. Walk every stepper and use the
  // tightest ``position_min`` and loosest ``position_max`` so the box
  // encloses every joint of multi-motor axes. Missing values fall
  // back to the parser defaults (``0`` / ``200``) so an incomplete
  // profile still renders a sensible rectangle.
  const perAxis = new Map()
  for (const stepper of steppers) {
    if (!stepper || typeof stepper !== 'object') continue
    const id = typeof stepper.id === 'string' ? stepper.id : ''
    // ``id`` is ``stepper_<letter>[<suffix>]`` — pull the letter.
    const letter = _axisLetterFromStepperId(id)
    if (!letter) continue

    const posMin = _coerceNumber(stepper.position_min, 0)
    const posMax = _coerceNumber(stepper.position_max, 200)

    const entry = perAxis.get(letter) || { min: posMin, max: posMax }
    entry.min = Math.min(entry.min, posMin)
    entry.max = Math.max(entry.max, posMax)
    perAxis.set(letter, entry)
  }

  if (!perAxis.has('x') || !perAxis.has('y')) return null

  const x = perAxis.get('x')
  const y = perAxis.get('y')
  // Reject degenerate / inverted ranges — a profile bug or a
  // half-populated JSON should not produce a box the operator
  // cannot read.
  if (x.max <= x.min || y.max <= y.min) return null

  return { xMin: x.min, xMax: x.max, yMin: y.min, yMax: y.max }
}

const _axisLetterFromStepperId = (id) => {
  if (!id) return null
  // Accept ``stepper_x``, ``stepper_x1``, ``stepper_x_back`` etc.
  const m = /^stepper_([a-z])(?:\d.*)?$/.exec(id)
  return m ? m[1] : null
}

const _coerceNumber = (value, fallback) => {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

const setMachineLimits = (limits) => {
  machineLimits.value = limits
  if (!limitsGroup) return

  // Dispose previous children. The group's geometry/material refs are
  // walked + disposed via the global scene.traverse() on unmount, but
  // we drop them now so a single limits switch does not accumulate
  // GPU buffers.
  while (limitsGroup.children.length) {
    const child = limitsGroup.children.pop()
    if (child.geometry) child.geometry.dispose()
    if (child.material) {
      if (Array.isArray(child.material)) {
        child.material.forEach((m) => m.dispose())
      } else {
        child.material.dispose()
      }
    }
  }

  if (!limits) return

  const { xMin, xMax, yMin, yMax } = limits

  // Outline rectangle on the X/Y plane. The 0.1 z-offset lifts the
  // line a hair above the CNC XY plane so it does not Z-fight with
  // the floor grid below. cncSpace is rotated by the parent group
  // so local Z maps to CNC Z.
  const OUTLINE_Z = 0.1
  const outlineGeom = new THREE.BufferGeometry()
  outlineGeom.setAttribute(
    'position',
    new THREE.Float32BufferAttribute(
      [
        xMin, yMin, OUTLINE_Z,
        xMax, yMin, OUTLINE_Z,
        xMax, yMax, OUTLINE_Z,
        xMin, yMax, OUTLINE_Z,
      ],
      3,
    ),
  )
  const outlineMat = new THREE.LineBasicMaterial({ color: 0xef4444 }) // Tailwind red-500
  const outline = new THREE.LineLoop(outlineGeom, outlineMat)
  limitsGroup.add(outline)

  // Floor grid — sized to the active work envelope, not a fixed
  // 500 mm square. Sits 0.05 z below the outline so the outline
  // always reads cleanly on top. GridHelper draws in its local XZ
  // plane by default; rotating it +π/2 around X aligns it with
  // cncSpace's local XY plane, and ``cncSpace`` then maps that to
  // the world XY floor (the orientation the operator expects for a
  // top-down view).
  const GRID_Z = 0.05
  const xSize = Math.max(xMax - xMin, 1)
  const ySize = Math.max(yMax - yMin, 1)
  const xDivisions = Math.max(1, Math.ceil(xSize / 10))
  const yDivisions = Math.max(1, Math.ceil(ySize / 10))
  const grid = new THREE.GridHelper(
    Math.max(xSize, 1),
    Math.max(xDivisions, 1),
    0x334155,
    0x334155,
  )
  grid.rotation.x = Math.PI / 2
  grid.position.set((xMin + xMax) / 2, (yMin + yMax) / 2, GRID_Z)
  limitsGroup.add(grid)
}

// ---------------------------------------------------------------------- //
// Program toolpath                                                         //
// ---------------------------------------------------------------------- //
//
// Watches ``store.status.file`` (basename of the interpreter's loaded
// program) and renders every move as a single ``LineSegments`` in
// the X/Y plane. Z moves are included but visually overlap with
// rapid Z raises on top of XY cuts — acceptable for now; a proper
// 3D toolpath lives in the next iteration.

const loadProgramToolpath = async (filename) => {
  if (!scene || !filename) return
  const basename = String(filename).split(/[\\/]/).pop()
  if (!basename || basename === lastLoadedFilename) return

  try {
    const text = await ProgramFilesService.readFile(basename)
    if (typeof text !== 'string') {
      clearToolpath()
      return
    }

    const segments = parseGcodeToolpath(text)
    if (!segments.length) {
      clearToolpath()
      lastLoadedFilename = basename
      toolpathMeta.value = { filename: basename, moves: 0 }
      return
    }

    replaceToolpathMesh(segments)
    lastLoadedFilename = basename
    toolpathMeta.value = { filename: basename, moves: segments.length }
  } catch (err) {
    // 404 / permission / network — drop any previous toolpath and
    // give up silently. The store + ActivePrintWidget surface the
    // load error to the operator; the viewer just reflects the
    // truth ("nothing loaded").
    clearToolpath()
    lastLoadedFilename = ''
  }
}

// Minimal G-code parser. Tracks modal motion (G0/G1/G2/G3) and
// distance mode (G90/G91) plus the running X/Y/Z position. For each
// line that touches one of those axes, emits one segment from the
// previous position to the new one. G2 / G3 arcs are linear
// approximated — a proper arc interpolator is out of scope here.
const parseGcodeToolpath = (text) => {
  const segments = []
  // Defaults mirror LinuxCNC's interpreter: absolute distances,
  // rapid motion. ``prevZ`` starts at 0 because the first move from
  // an unknown Z is treated as a lateral slide at the workpiece top.
  let motion = 0   // 0 = G0 (rapid), 1 = G1 (cut), 2 = G2 (cw), 3 = G3 (ccw)
  let absolute = true
  let curX = 0
  let curY = 0
  let curZ = 0
  let hasPosition = false

  const lines = text.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]
    if (!raw) continue

    // Strip line comments (``;`` and the inline ``(`` ... ``)`` form).
    // Paren stripping is naive — a multi-line ``(`` comment would
    // leak — but LinuxCNC G-code files rarely contain those, and the
    // parser is intentionally minimal for now.
    let cleaned = raw
    const semi = cleaned.indexOf(';')
    if (semi >= 0) cleaned = cleaned.slice(0, semi)
    cleaned = cleaned.replace(/\(.*?\)/g, '').trim()
    if (!cleaned) continue

    const tokens = cleaned.split(/\s+/)
    let newX = null
    let newY = null
    let newZ = null

    for (const token of tokens) {
      if (!token) continue
      const letter = token[0].toUpperCase()
      const rest = token.slice(1)
      const value = Number(rest)
      const numeric = Number.isFinite(value)

      switch (letter) {
        case 'G':
          if (numeric) {
            if (value === 0) motion = 0
            else if (value === 1) motion = 1
            else if (value === 2) motion = 2
            else if (value === 3) motion = 3
            else if (value === 90) absolute = true
            else if (value === 91) absolute = false
          }
          break
        case 'X':
          if (numeric) {
            newX = absolute ? value : curX + value
          }
          break
        case 'Y':
          if (numeric) {
            newY = absolute ? value : curY + value
          }
          break
        case 'Z':
          if (numeric) {
            newZ = absolute ? value : curZ + value
          }
          break
        default:
          break
      }
    }

    if (newX === null && newY === null && newZ === null) continue

    const prevX = curX
    const prevY = curY
    const prevZ = curZ
    if (newX !== null) curX = newX
    if (newY !== null) curY = newY
    if (newZ !== null) curZ = newZ

    // Skip the very first point — there's no "previous" to draw from
    // until we know where the tool started. The next line with a
    // move emits the first segment from (0,0,0).
    if (!hasPosition) {
      hasPosition = true
      continue
    }

    segments.push(prevX, prevY, prevZ, curX, curY, curZ)
    // ``motion`` is intentionally not used to colour the lines (the
    // user picked "single color, all G0/G1/G2/G3"). Future iteration
    // can branch here to draw rapid + cut as separate meshes.
    void motion
  }

  return segments
}

const replaceToolpathMesh = (segments) => {
  clearToolpathMesh()

  // Apply the active work origin to every vertex so the toolpath
  // lands where the cut actually happens. ``g5x_offset`` carries
  // the active G54..G59.3 origin; ``g92_offset`` is the additive
  // origin (zero unless the operator has set G92). Sum them
  // per-axis — the result is the effective work origin the
  // interpreter applies at runtime. ``tool_offset`` is intentionally
  // left out of this calculation: it shifts the Z DRO display but
  // does not move the cut.
  let dx = 0, dy = 0, dz = 0
  if (props.applyWorkingOffset) {
    const g5x = store.status.g5x_offset || []
    const g92 = store.status.g92_offset || []
    dx = (Number(g5x[0]) || 0) + (Number(g92[0]) || 0)
    dy = (Number(g5x[1]) || 0) + (Number(g92[1]) || 0)
    dz = (Number(g5x[2]) || 0) + (Number(g92[2]) || 0)
  }

  const offset = new Float32Array(segments.length)
  for (let i = 0; i < segments.length; i++) {
    const axis = i % 3
    const delta = axis === 0 ? dx : axis === 1 ? dy : dz
    offset[i] = segments[i] + delta
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute(
    'position',
    new THREE.Float32BufferAttribute(offset, 3),
  )
  const material = new THREE.LineBasicMaterial({ color: 0x60a5fa })
  toolpathLine = new THREE.LineSegments(geometry, material)

  // ``cncSpace`` is the rotated parent group — the same coordinate
  // system the toolhead lives in. Children added directly share
  // the rotation, so positions are emitted in CNC X/Y/Z.
  scene.children[0].add(toolpathLine)
}

const clearToolpathMesh = () => {
  if (!toolpathLine) return
  if (toolpathLine.geometry) toolpathLine.geometry.dispose()
  if (toolpathLine.material) toolpathLine.material.dispose()
  if (toolpathLine.parent) toolpathLine.parent.remove(toolpathLine)
  toolpathLine = null
}

const clearToolpath = () => {
  clearToolpathMesh()
  lastLoadedFilename = ''
  toolpathMeta.value = { filename: '', moves: 0 }
}

const animate = () => {
  animationFrameId = requestAnimationFrame(animate)
  controls.update() // Required if enableDamping is true
  renderer.render(scene, camera)
}
</script>

<template>
  <div class="w-full h-full relative overflow-hidden rounded-lg">
    <div ref="container" class="absolute inset-0"></div>

    <!-- UI Overlay for Viewer Info -->
    <div class="absolute top-4 left-4 pointer-events-none">
      <div class="bg-gray-900/80 backdrop-blur text-xs text-gray-300 px-3 py-1.5 rounded border border-gray-700 shadow font-mono">
        <div class="font-semibold text-gray-100">Ngc Coordinate System Viewer</div>
        <div class="mt-0.5 text-gray-400">
          <template v-if="machineLimits">
            X {{ machineLimits.xMin }}–{{ machineLimits.xMax }} mm
            · Y {{ machineLimits.yMin }}–{{ machineLimits.yMax }} mm
          </template>
          <template v-else>
            limits: not configured
          </template>
          <template v-if="toolpathMeta.moves > 0">
            · N moves {{ toolpathMeta.moves }}
          </template>
          <template v-if="props.applyWorkingOffset && (store.status.g5x_offset || store.status.g92_offset)">
            · offset
            G5x ({{ formatOffset(store.status.g5x_offset) }})
            + G92 ({{ formatOffset(store.status.g92_offset) }})
          </template>
        </div>
      </div>
    </div>
  </div>
</template>