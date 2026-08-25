<script setup lang="ts">
// NgcCoordinateSystemViewer — Three.js toolpath viewer for the dashboard.
//
// Renders three things on top of the standard grid + axes + toolhead
// rig the original component shipped with:
//
//   1. A wireframe "limits box" in the X/Y plane drawn from the
//      machine limits declared in the active `hardware.json`
//      (`axes[].position_max`).
//
//   2. The currently loaded G-code / NGC program's toolpath, fetched
//      from `/api/v1/programs/content/{filename}`.
//
//   3. A small overlay showing the active limits and the move count.
//
// Per-segment coordinate system handling:
//
//   The parser tags every emitted motion segment with the work
//   coordinate system (G54..G59.3 → ``wcsIndex`` 1..9) and the
//   in-program G92 additive offset that was active when the segment
//   was emitted. At draw time the active WCS origin from telemetry
//   (``store.status.g5xOffset``) is added on top of the segment's
//   own G92 plus the live ``store.status.g92Offset`` from telemetry.
//   The Set-Position modal mutates the active WCS via ``G10 L20 P0``
//   MDI; the resulting ``g5x_offset`` delta from the servo thread
//   triggers a redraw so the toolpath moves with the new origin.
//
//   Non-active WCSes (e.g. a G55 section while G54 is selected in
//   the DRO dropdown) are drawn at machine origin instead of their
//   true WCS origin because the backend only exposes the active
//   WCS's per-axis offsets in telemetry. For files that mostly use
//   a single WCS this is invisible; for mixed-WCS files the user
//   should switch the active WCS to the system the file uses
//   before relying on the preview.

import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { useMachineStore } from '../stores/machine'
import { useMachineConfigStore } from '../modules/machineconfig/store'
import { ProgramFilesService } from '../../generated/api/services/ProgramFilesService'

// --- Interfaces & Types ---
interface MachineLimits {
  xMin: number
  xMax: number
  yMin: number
  yMax: number
}

interface ToolpathMeta {
  filename: string
  moves: number
}

/**
 * One motion segment with the per-segment parser state captured at
 * the moment it was emitted. ``wcsIndex`` is 1..9 (G54..G59.3);
 * ``g92`` is the additive origin that was active when the line was
 * parsed (and zeroed if a G92.2 suspension was in effect).
 */
interface ParsedSegment {
  from: [number, number, number]
  to:   [number, number, number]
  wcsIndex: number
  g92:    [number, number, number]
}

// Typing the loosely parsed hardware.json payload
interface HardwareJsonAxis {
  id?: string
  position_max?: string | number
  position_min?: string | number
  position_endstop?: string | number
}

interface HardwareJsonPayload {
  axes?: HardwareJsonAxis[]
  [key: string]: any
}

// --- Props ---
const props = withDefaults(
    defineProps<{
      /**
       * Whether the rendered toolpath should be offset by the
       * interpreter's active work origin (g5x_offset plus the
       * optional g92_offset additive origin).
       */
      applyWorkingOffset?: boolean
    }>(),
    { applyWorkingOffset: true }
)

const store = useMachineStore()
const machineconfigStore = useMachineConfigStore()

// Template ref for the container div
const container = ref<HTMLDivElement | null>(null)

// --- Three.js Instances ---
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let renderer: THREE.WebGLRenderer | null = null
let controls: OrbitControls | null = null
let toolheadGroup: THREE.Group | null = null
let toolheadMesh: THREE.Mesh | null = null
let limitsGroup: THREE.Group | null = null
let toolpathLine: THREE.LineSegments | null = null
let wcsMarkerGroup: THREE.Group | null = null
let animationFrameId: number = 0
let resizeObserver: ResizeObserver | null = null

// --- Reactive UI state ---
const machineLimits = ref<MachineLimits | null>(null)
const toolpathMeta = ref<ToolpathMeta>({ filename: '', moves: 0 })

// --- Tracking Helpers ---
let lastLoadedFilename = ''

// Cache of parsed segments keyed by basename so offset ticks don't
// refetch + reparse. ``loadProgramToolpath`` only re-reads the file
// when the basename is not in the cache; ``redrawToolpath`` walks
// the cache in place and rebuilds the geometry.
const parsedCache = new Map<string, ParsedSegment[]>()

// --- Coordinate-system helpers ---

// Mirror of ``WORK_COORDINATE_SYSTEMS`` from ``config/gcodes.ts`` so
// the viewer can name the active WCS without pulling in a module
// config surface. Index 1..9 → G54..G59.3.
const wcsNameForIndex = (idx: number): string => {
  if (idx === 7) return 'G59.1'
  if (idx === 8) return 'G59.2'
  if (idx === 9) return 'G59.3'
  if (idx >= 1 && idx <= 6) return `G${53 + idx}`
  return 'G54'
}

// Formatting helper for the overlay
const formatOffset = (axis: number[] | null | undefined): string => {
  if (!Array.isArray(axis) || axis.length < 3) return '0,0,0'
  const fmt = (n: number) => (Number.isFinite(n) ? n.toFixed(2) : '0')
  return `${fmt(axis[0])},${fmt(axis[1])},${fmt(axis[2])}`
}

// Reactive views over the live telemetry. ``g5xOffset`` is the
// ACTIVE system's per-axis offsets for X,Y,Z,A,B,C,U,V,W (see the
// backend mapper); the viewer only consumes the first three.
const activeWcsIdx = computed<number>(() => {
  const n = Number(store.status.g5xIndex)
  if (!Number.isFinite(n) || n < 1 || n > 9) return 1
  return Math.floor(n)
})

const activeWcsName = computed(() => wcsNameForIndex(activeWcsIdx.value))

const activeWcsOffset = computed<[number, number, number]>(() => {
  const t = store.status.g5xOffset
  if (!Array.isArray(t)) return [0, 0, 0]
  return [Number(t[0]) || 0, Number(t[1]) || 0, Number(t[2]) || 0]
})

const liveG92 = computed<[number, number, number]>(() => {
  const t = store.status.g92Offset
  if (!Array.isArray(t)) return [0, 0, 0]
  return [Number(t[0]) || 0, Number(t[1]) || 0, Number(t[2]) || 0]
})

onMounted(async () => {
  initThreeJS()
  setupWatchers()
  animate()

  await loadMachineLimits()

  if (typeof store.status.file === 'string' && store.status.file.length > 0) {
    await loadProgramToolpath(store.status.file)
  }
})

onBeforeUnmount(() => {
  if (animationFrameId) cancelAnimationFrame(animationFrameId)

  if (resizeObserver && container.value) {
    resizeObserver.unobserve(container.value)
  }

  if (renderer) renderer.dispose()

  if (scene) {
    scene.traverse((object: THREE.Object3D) => {
      const mesh = object as THREE.Mesh
      if (!mesh.isMesh && !(object as any).isLine && !(object as any).isLineSegments) return

      if (mesh.geometry) mesh.geometry.dispose()

      if (mesh.material) {
        if (Array.isArray(mesh.material)) {
          mesh.material.forEach(cleanMaterial)
        } else {
          cleanMaterial(mesh.material)
        }
      }
    })
  }

  if (controls) controls.dispose()
})

const cleanMaterial = (material: THREE.Material) => {
  material.dispose()
  for (const key of Object.keys(material)) {
    const value = (material as any)[key]
    if (value && typeof value === 'object' && 'minFilter' in value) {
      value.dispose()
    }
  }
}

const initThreeJS = () => {
  if (!container.value) return

  const width = container.value.clientWidth
  const height = container.value.clientHeight

  scene = new THREE.Scene()
  scene.background = new THREE.Color('#1f2937') // Tailwind gray-800

  // CRITICAL: Map Three.js Y-up to LinuxCNC Z-up
  const cncSpace = new THREE.Group()
  cncSpace.rotation.x = -Math.PI / 2 // Rotate -90 degrees on X
  scene.add(cncSpace)

  camera = new THREE.PerspectiveCamera(45, width / height, 1, 10000)
  camera.position.set(200, 200, 200)
  camera.lookAt(0, 0, 0)

  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(width, height)
  renderer.setPixelRatio(window.devicePixelRatio)
  container.value.appendChild(renderer.domElement)

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.05

  // Environment Helpers
  const axesHelper = new THREE.AxesHelper(100)
  cncSpace.add(axesHelper)

  // Toolhead Mesh
  toolheadGroup = new THREE.Group()
  const geometry = new THREE.ConeGeometry(5, 20, 16)
  geometry.rotateX(-Math.PI / 2)
  geometry.translate(0, 0, 10)

  const material = new THREE.MeshBasicMaterial({
    color: 0xef4444,
    wireframe: false,
    transparent: true,
    opacity: 0.8
  })

  toolheadMesh = new THREE.Mesh(geometry, material)
  toolheadGroup.add(toolheadMesh)
  cncSpace.add(toolheadGroup)

  updateToolheadPosition()

  // Limits box group
  limitsGroup = new THREE.Group()
  cncSpace.add(limitsGroup)

  // Active WCS origin marker. Populated by updateWcsMarker() on
  // every redraw so the cross tracks the runtime origin from
  // telemetry (i.e. it follows Set-Position edits).
  wcsMarkerGroup = new THREE.Group()
  cncSpace.add(wcsMarkerGroup)

  // Resize Handling
  resizeObserver = new ResizeObserver(entries => {
    if (!renderer || !camera) return
    for (const entry of entries) {
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
  if (!toolheadGroup || !store.status.position) return
  const [x, y, z] = store.status.position
  toolheadGroup.position.set(x, y, z)
}

const setupWatchers = () => {
  watch(() => store.status.position, () => {
    updateToolheadPosition()
  }, { deep: true })

  watch(() => store.status.file, async (newFile) => {
    if (typeof newFile === 'string' && newFile.length > 0) {
      await loadProgramToolpath(newFile)
      await loadMachineLimits()
    } else {
      clearToolpath()
    }
  })

  watch(
      () => [
        store.status.g5xIndex,
        store.status.g5xOffset?.slice(0, 3),
        store.status.g92Offset?.slice(0, 3),
      ],
      () => {
        // No refetch + reparse: the cached segments are walked in
        // place with the new offsets. This is the path the
        // Set-Position modal ends up on after its MDI round-trip
        // flips a bit of g5x_offset in the telemetry stream.
        if (lastLoadedFilename) redrawToolpath()
      },
      { deep: true },
  )

  watch(() => machineconfigStore.activeListing?.machine_name, async (name) => {
    if (typeof name === 'string' && name.length > 0) {
      await loadMachineLimits()
    }
  })
}

// ---------------------------------------------------------------------- //
// Machine limits box & Custom Rectangular Grid                           //
// ---------------------------------------------------------------------- //

const loadMachineLimits = async () => {
  if (!scene) return

  try {
    const response = await machineconfigStore.readActiveFileContent('hardware.json')
    const text = typeof response === 'string' ? response : ''
    if (!text) {
      setMachineLimits(null)
      return
    }

    let payload: HardwareJsonPayload
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
    setMachineLimits(null)
  }
}

const _extractLimitsFromHardwareJson = (payload: HardwareJsonPayload): MachineLimits | null => {
  if (!payload || typeof payload !== 'object') return null

  const axes = Array.isArray(payload.axes) ? payload.axes : []
  if (!axes.length) return null

  const perAxis = new Map<string, { min: number; max: number }>()

  for (const axis of axes) {
    if (!axis || typeof axis !== 'object') continue
    const letter = typeof axis.id === 'string' ? axis.id.toLowerCase() : ''
    if (letter !== 'x' && letter !== 'y') continue

    const posMin = _coerceNumber(axis.position_min, 0)
    const posMax = _coerceNumber(axis.position_max, 200)

    perAxis.set(letter, { min: posMin, max: posMax })
  }

  if (!perAxis.has('x') || !perAxis.has('y')) return null

  const x = perAxis.get('x')!
  const y = perAxis.get('y')!

  if (x.max <= x.min || y.max <= y.min) return null

  return { xMin: x.min, xMax: x.max, yMin: y.min, yMax: y.max }
}

const _coerceNumber = (value: any, fallback: number): number => {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

const setMachineLimits = (limits: MachineLimits | null) => {
  machineLimits.value = limits
  if (!limitsGroup) return

  // Dispose previous children
  while (limitsGroup.children.length) {
    const child = limitsGroup.children.pop() as THREE.Mesh | THREE.LineSegments
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

  // 1. Outline rectangle
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
  const outlineMat = new THREE.LineBasicMaterial({ color: 0xef4444 })
  const outline = new THREE.LineLoop(outlineGeom, outlineMat)
  limitsGroup.add(outline)

  // 2. Custom Rectangular Floor Grid
  const GRID_Z = 0.05
  const xSize = Math.max(xMax - xMin, 1)
  const ySize = Math.max(yMax - yMin, 1)

  // Calculate divisions for roughly 10x10 squares
  const xDivisions = Math.max(1, Math.ceil(xSize / 10))
  const yDivisions = Math.max(1, Math.ceil(ySize / 10))

  const gridPoints: THREE.Vector3[] = []
  const stepX = xSize / xDivisions
  const stepY = ySize / yDivisions

  // Draw vertical lines (constant X, varying Y)
  for (let i = 0; i <= xDivisions; i++) {
    const x = xMin + (i * stepX)
    gridPoints.push(new THREE.Vector3(x, yMin, GRID_Z))
    gridPoints.push(new THREE.Vector3(x, yMax, GRID_Z))
  }

  // Draw horizontal lines (constant Y, varying X)
  for (let j = 0; j <= yDivisions; j++) {
    const y = yMin + (j * stepY)
    gridPoints.push(new THREE.Vector3(xMin, y, GRID_Z))
    gridPoints.push(new THREE.Vector3(xMax, y, GRID_Z))
  }

  const gridGeometry = new THREE.BufferGeometry().setFromPoints(gridPoints)
  const gridMaterial = new THREE.LineBasicMaterial({
    color: 0x334155, // Tailwind slate-700
    depthWrite: false
  })

  const grid = new THREE.LineSegments(gridGeometry, gridMaterial)
  limitsGroup.add(grid)
}

// ---------------------------------------------------------------------- //
// Program toolpath                                                       //
// ---------------------------------------------------------------------- //

const loadProgramToolpath = async (filename: string) => {
  if (!scene || !filename) return
  const basename = String(filename).split(/[\\/]/).pop()
  if (!basename) return

  // Only refetch + reparse when we don't already have this file in
  // the cache. The previous implementation also short-circuited
  // when ``basename === lastLoadedFilename``, which inadvertently
  // blocked the offset-redraw path: the watcher fires on every
  // g5x_offset delta, so its callback has to take the "use cache"
  // branch instead of going through this loader. ``redrawToolpath``
  // is that callback.
  if (!parsedCache.has(basename)) {
    try {
      const text = await ProgramFilesService.readFile(basename)
      if (typeof text !== 'string') {
        clearToolpath()
        return
      }
      const parsed = parseGcodeToolpath(text)
      parsedCache.set(basename, parsed)
    } catch (err) {
      clearToolpath()
      return
    }
  }

  const segments = parsedCache.get(basename) || []
  lastLoadedFilename = basename
  toolpathMeta.value = { filename: basename, moves: segments.length }
  redrawToolpath()
}

const redrawToolpath = () => {
  if (!scene || !lastLoadedFilename) return
  const segments = parsedCache.get(lastLoadedFilename)
  if (!segments) return
  replaceToolpathMesh(segments)
  updateWcsMarker()
}

const parseGcodeToolpath = (text: string): ParsedSegment[] => {
  const segments: ParsedSegment[] = []
  let motion = 0
  let absolute = true
  let curX = 0
  let curY = 0
  let curZ = 0
  let hasPosition = false

  // Per-file parser state. ``activeWcs`` is the 1-based index into
  // the G5x table (1..9 → G54..G59.3). ``g92`` is the additive
  // ``G92`` origin that is currently applied; ``g92Snapshot``
  // remembers the value just before ``G92.2`` so ``G92.3`` can
  // restore it. ``pendingG92`` is set by the G-word loop and
  // resolved after the axis tokens on the same line — ``G92``
  // takes its axis values from the same line they appear on, so a
  // single pass through the tokens would otherwise lose them.
  let activeWcs: number = 1
  let g92: [number, number, number] = [0, 0, 0]
  const g92Snapshot: [number, number, number] = [0, 0, 0]
  let g92Suspended = false
  let pendingG92: 'set' | 'clear' | 'suspend' | 'resume' | null = null

  const lines = text.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]
    if (!raw) continue

    let cleaned = raw
    const semi = cleaned.indexOf(';')
    if (semi >= 0) cleaned = cleaned.slice(0, semi)
    cleaned = cleaned.replace(/\(.*?\)/g, '').trim()
    if (!cleaned) continue

    const tokens = cleaned.split(/\s+/)
    let newX: number | null = null
    let newY: number | null = null
    let newZ: number | null = null
    pendingG92 = null

    for (const token of tokens) {
      if (!token) continue
      const letter = token[0].toUpperCase()
      const rest = token.slice(1)
      const value = Number(rest)
      const numeric = Number.isFinite(value)

      switch (letter) {
        case 'G': {
          if (!numeric) break

          // Modal work-coordinate-system selectors.
          const wcs = gwordToWcsIndex(value)
          if (wcs !== null) {
            activeWcs = wcs
            break
          }

          if (value === 0) motion = 0
          else if (value === 1) motion = 1
          else if (value === 2) motion = 2
          else if (value === 3) motion = 3
          else if (value === 90) absolute = true
          else if (value === 91) absolute = false
          else if (value === 92) {
            pendingG92 = 'set'
            g92Suspended = false
          }
          else if (Math.abs(value - 92.1) < 1e-9) pendingG92 = 'clear'
          else if (Math.abs(value - 92.2) < 1e-9) pendingG92 = 'suspend'
          else if (Math.abs(value - 92.3) < 1e-9) pendingG92 = 'resume'
          break
        }
        case 'X':
          if (numeric) newX = absolute ? value : curX + value
          break
        case 'Y':
          if (numeric) newY = absolute ? value : curY + value
          break
        case 'Z':
          if (numeric) newZ = absolute ? value : curZ + value
          break
      }
    }

    // Resolve the G92 family. ``G92 X.. Y.. Z..`` only touches the
    // axes it explicitly mentions — omitted axes keep their current
    // value. ``G92.1`` zeros everything, ``G92.2`` suspends (G92
    // contribution becomes 0 until G92.3 resumes it), ``G92.3``
    // restores the snapshot taken at suspend time.
    if (pendingG92) {
      if (pendingG92 === 'set') {
        for (const token of tokens) {
          if (!token) continue
          const letter = token[0].toUpperCase()
          if (letter !== 'X' && letter !== 'Y' && letter !== 'Z') continue
          const v = Number(token.slice(1))
          if (!Number.isFinite(v)) continue
          if (letter === 'X') g92[0] = v
          else if (letter === 'Y') g92[1] = v
          else g92[2] = v
        }
      } else if (pendingG92 === 'clear') {
        g92[0] = 0; g92[1] = 0; g92[2] = 0
        g92Snapshot[0] = 0; g92Snapshot[1] = 0; g92Snapshot[2] = 0
        g92Suspended = false
      } else if (pendingG92 === 'suspend') {
        g92Snapshot[0] = g92[0]; g92Snapshot[1] = g92[1]; g92Snapshot[2] = g92[2]
        g92Suspended = true
      } else if (pendingG92 === 'resume') {
        g92[0] = g92Snapshot[0]; g92[1] = g92Snapshot[1]; g92[2] = g92Snapshot[2]
        g92Suspended = false
      }
      pendingG92 = null
      // G92 lines never produce a motion segment.
      continue
    }

    if (newX === null && newY === null && newZ === null) continue

    const prevX = curX
    const prevY = curY
    const prevZ = curZ
    if (newX !== null) curX = newX
    if (newY !== null) curY = newY
    if (newZ !== null) curZ = newZ

    if (!hasPosition) {
      hasPosition = true
      continue
    }

    // While G92.2 is in effect, the G92 contribution is zero.
    const effectiveG92: [number, number, number] = g92Suspended
      ? [0, 0, 0]
      : [g92[0], g92[1], g92[2]]

    segments.push({
      from: [prevX, prevY, prevZ],
      to:   [curX,  curY,  curZ],
      wcsIndex: activeWcs,
      g92: effectiveG92,
    })
    void motion
  }

  return segments
}

// Map a G-word numeric value to a work-coordinate-system index
// (1..9) when it is a system-select, or null otherwise.
const gwordToWcsIndex = (value: number): number | null => {
  if (!Number.isFinite(value)) return null
  if (value >= 54 && value <= 59) return Math.floor(value) - 53
  if (Math.abs(value - 59.1) < 1e-9) return 7
  if (Math.abs(value - 59.2) < 1e-9) return 8
  if (Math.abs(value - 59.3) < 1e-9) return 9
  return null
}

const replaceToolpathMesh = (segments: ParsedSegment[]) => {
  clearToolpathMesh()

  const activeIdx = activeWcsIdx.value
  const runtimeG5x = props.applyWorkingOffset ? activeWcsOffset.value : [0, 0, 0]
  const runtimeG92 = props.applyWorkingOffset ? liveG92.value : [0, 0, 0]

  const flat = new Float32Array(segments.length * 6)
  let i = 0
  for (const seg of segments) {
    // Only the segment's active WCS gets the live g5xOffset from
    // telemetry. Other systems would need their own offsets, which
    // the backend doesn't expose (it only ships the active WCS's
    // per-axis offsets). For the typical single-WCS case this is
    // exactly right; for G54+G55 mixes the non-active sections
    // render at machine origin, which is a known limitation of
    // telemetry-only data — see the file header.
    let g5xX = 0, g5xY = 0, g5xZ = 0
    if (seg.wcsIndex === activeIdx) {
      g5xX = runtimeG5x[0]
      g5xY = runtimeG5x[1]
      g5xZ = runtimeG5x[2]
    }

    // Program-level G92 is always additive on top of the WCS
    // origin; the live G92 from telemetry adds on top of that.
    const dx = g5xX + seg.g92[0] + runtimeG92[0]
    const dy = g5xY + seg.g92[1] + runtimeG92[1]
    const dz = g5xZ + seg.g92[2] + runtimeG92[2]

    flat[i++] = seg.from[0] + dx
    flat[i++] = seg.from[1] + dy
    flat[i++] = seg.from[2] + dz
    flat[i++] = seg.to[0] + dx
    flat[i++] = seg.to[1] + dy
    flat[i++] = seg.to[2] + dz
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute(
      'position',
      new THREE.Float32BufferAttribute(flat, 3),
  )
  const material = new THREE.LineBasicMaterial({ color: 0x60a5fa })
  toolpathLine = new THREE.LineSegments(geometry, material)

  if (scene) scene.children[0].add(toolpathLine)
}

const clearToolpathMesh = () => {
  if (!toolpathLine) return
  if (toolpathLine.geometry) toolpathLine.geometry.dispose()
  if (toolpathLine.material) {
    if (Array.isArray(toolpathLine.material)) {
      toolpathLine.material.forEach((m) => m.dispose())
    } else {
      toolpathLine.material.dispose()
    }
  }
  if (toolpathLine.parent) toolpathLine.parent.remove(toolpathLine)
  toolpathLine = null
}

const clearToolpath = () => {
  clearToolpathMesh()
  // Drop the previously-loaded file's parsed segments so we don't
  // leak memory when the user unloads a program or swaps to a new
  // one. The cache is intentionally per-file; the watcher re-fires
  // loadProgramToolpath when ``store.status.file`` changes, which
  // is the only path that inserts into the cache.
  if (lastLoadedFilename) parsedCache.delete(lastLoadedFilename)
  if (wcsMarkerGroup) {
    while (wcsMarkerGroup.children.length) {
      const child = wcsMarkerGroup.children.pop()
      if (child.geometry) child.geometry.dispose()
      if (child.material) {
        if (Array.isArray(child.material)) {
          child.material.forEach((m) => m.dispose())
        } else {
          child.material.dispose()
        }
      }
    }
  }
  lastLoadedFilename = ''
  toolpathMeta.value = { filename: '', moves: 0 }
}

// Redraws the active WCS origin marker from the live telemetry.
// Three short colored axis arms (red X, green Y, blue Z) at the
// origin position; the WCS name (G54, G55, …) is shown in the
// text overlay so we don't need a 3D sprite for the label.
const WCS_MARKER_ARM_LENGTH = 12

const updateWcsMarker = () => {
  if (!wcsMarkerGroup) return

  while (wcsMarkerGroup.children.length) {
    const child = wcsMarkerGroup.children.pop()
    if (child.geometry) child.geometry.dispose()
    if (child.material) {
      if (Array.isArray(child.material)) {
        child.material.forEach((m) => m.dispose())
      } else {
        child.material.dispose()
      }
    }
  }

  if (!props.applyWorkingOffset) return

  const [ox, oy, oz] = activeWcsOffset.value
  const arms: Array<{ dx: number; dy: number; dz: number; color: number }> = [
    { dx: WCS_MARKER_ARM_LENGTH, dy: 0, dz: 0, color: 0xef4444 },
    { dx: 0, dy: WCS_MARKER_ARM_LENGTH, dz: 0, color: 0x22c55e },
    { dx: 0, dy: 0, dz: WCS_MARKER_ARM_LENGTH, color: 0x3b82f6 },
  ]

  for (const arm of arms) {
    const g = new THREE.BufferGeometry()
    g.setAttribute(
        'position',
        new THREE.Float32BufferAttribute(
            [
              ox, oy, oz,
              ox + arm.dx, oy + arm.dy, oz + arm.dz,
            ],
            3,
        ),
    )
    const m = new THREE.LineBasicMaterial({ color: arm.color })
    wcsMarkerGroup.add(new THREE.LineSegments(g, m))
  }
}

const animate = () => {
  animationFrameId = requestAnimationFrame(animate)
  if (controls) controls.update()
  if (renderer && scene && camera) renderer.render(scene, camera)
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
          <template v-if="props.applyWorkingOffset && (store.status.g5xOffset || store.status.g92Offset)">
            · offset
            G5x={{ activeWcsName }} ({{ formatOffset(activeWcsOffset) }})
            + G92 ({{ formatOffset(liveG92) }})
          </template>
        </div>
      </div>
    </div>
  </div>
</template>