<script setup lang="ts">
// NgcCoordinateSystemViewer — Three.js toolpath viewer for the dashboard.
//
// Renders three things on top of the standard grid + axes + toolhead
// rig the original component shipped with:
//
//   1. A wireframe "limits box" in the X/Y plane drawn from the
//      machine limits declared in the active `hardware.json`
//      (`axes[].steppers[].position_min` / `position_max`).
//
//   2. The currently loaded G-code / NGC program's toolpath, fetched
//      from `/api/v1/programs/content/{filename}`.
//
//   3. A small overlay showing the active limits and the move count.

import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
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

// Typing the loosely parsed hardware.json payload
interface HardwareJsonStepper {
  id?: string
  position_min?: string | number
  position_max?: string | number
}

interface HardwareJsonPayload {
  steppers?: HardwareJsonStepper[]
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
let animationFrameId: number = 0
let resizeObserver: ResizeObserver | null = null

// --- Reactive UI state ---
const machineLimits = ref<MachineLimits | null>(null)
const toolpathMeta = ref<ToolpathMeta>({ filename: '', moves: 0 })

// --- Tracking Helpers ---
let lastLoadedFilename = ''

// Formatting helper for the overlay
const formatOffset = (axis: number[] | null | undefined): string => {
  if (!Array.isArray(axis) || axis.length < 3) return '0,0,0'
  const fmt = (n: number) => (Number.isFinite(n) ? n.toFixed(2) : '0')
  return `${fmt(axis[0])},${fmt(axis[1])},${fmt(axis[2])}`
}

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
        store.status.g5x_offset?.slice(0, 3),
        store.status.g92_offset?.slice(0, 3),
      ],
      async () => {
        if (lastLoadedFilename) {
          await loadProgramToolpath(lastLoadedFilename)
        }
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

  const steppers = Array.isArray(payload.steppers) ? payload.steppers : []
  if (!steppers.length) return null

  const perAxis = new Map<string, { min: number; max: number }>()

  for (const stepper of steppers) {
    if (!stepper || typeof stepper !== 'object') continue
    const id = typeof stepper.id === 'string' ? stepper.id : ''
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

  const x = perAxis.get('x')!
  const y = perAxis.get('y')!

  if (x.max <= x.min || y.max <= y.min) return null

  return { xMin: x.min, xMax: x.max, yMin: y.min, yMax: y.max }
}

const _axisLetterFromStepperId = (id: string): string | null => {
  if (!id) return null
  const m = /^stepper_([a-z])(?:\d.*)?$/.exec(id)
  return m ? m[1] : null
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
    toolpathMeta.value = { filename: basename, moves: segments.length / 6 } // 6 coordinates per segment
  } catch (err) {
    clearToolpath()
    lastLoadedFilename = ''
  }
}

const parseGcodeToolpath = (text: string): number[] => {
  const segments: number[] = []
  let motion = 0
  let absolute = true
  let curX = 0
  let curY = 0
  let curZ = 0
  let hasPosition = false

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

    segments.push(prevX, prevY, prevZ, curX, curY, curZ)
    void motion
  }

  return segments
}

const replaceToolpathMesh = (segments: number[]) => {
  clearToolpathMesh()

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
  lastLoadedFilename = ''
  toolpathMeta.value = { filename: '', moves: 0 }
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