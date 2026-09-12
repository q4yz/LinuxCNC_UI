<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { storeToRefs } from 'pinia'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { useMachineStore } from '../stores/machine'
import { useBaseThreadStore } from '../stores/baseThread'
import { ProgramFilesService } from '../../generated/api/services/ProgramFilesService'
import { WORK_COORDINATE_SYSTEMS } from '../config/gcodes'
import { parseGcodeToolpath } from '../parsers/gcodeParser'
import type { ParsedSegment } from '../parsers/gcodeParser'
import { MacroButton, useMacroButtonConfig } from '../ui'
import { useRenderQuality } from '../composables/useRenderQuality'


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

type CameraMode = 'default' | 'top' | 'front' | 'side' | 'free'

const MAX_JOG_SPEED = 3.3

const activeKeyBindings = computed<Record<string, { axis: number; direction: number }>>(() => {
  const mode = cameraMode.value

  if (mode === 'front') {
    // XZ Plane: Visual Left/Right = X, Visual Up/Down = Z. Depth = Y.
    return {
      ArrowLeft:  { axis: 0, direction: -1 },
      ArrowRight: { axis: 0, direction: +1 },
      ArrowUp:    { axis: 2, direction: +1 },
      ArrowDown:  { axis: 2, direction: -1 },
      Numpad4:    { axis: 0, direction: -1 },
      Numpad6:    { axis: 0, direction: +1 },
      Numpad8:    { axis: 2, direction: +1 },
      Numpad2:    { axis: 2, direction: -1 },

      PageUp:     { axis: 1, direction: -1 }, // Move towards camera
      PageDown:   { axis: 1, direction: +1 }, // Move away from camera
      Numpad9:    { axis: 1, direction: -1 },
      Numpad3:    { axis: 1, direction: +1 },
    }
  }

  if (mode === 'side') {
    // YZ Plane: Visual Left/Right = Y, Visual Up/Down = Z. Depth = X.
    return {
      ArrowLeft:  { axis: 1, direction: -1 },
      ArrowRight: { axis: 1, direction: +1 },
      ArrowUp:    { axis: 2, direction: +1 },
      ArrowDown:  { axis: 2, direction: -1 },
      Numpad4:    { axis: 1, direction: -1 },
      Numpad6:    { axis: 1, direction: +1 },
      Numpad8:    { axis: 2, direction: +1 },
      Numpad2:    { axis: 2, direction: -1 },

      PageUp:     { axis: 0, direction: +1 }, // Move towards camera
      PageDown:   { axis: 0, direction: -1 }, // Move away from camera
      Numpad9:    { axis: 0, direction: +1 },
      Numpad3:    { axis: 0, direction: -1 },
    }
  }

  // Default / Free / Top (XY Plane)
  // Visual Left/Right = X, Visual Up/Down = Y. Depth = Z.
  return {
    ArrowLeft:  { axis: 0, direction: -1 },
    ArrowRight: { axis: 0, direction: +1 },
    ArrowUp:    { axis: 1, direction: +1 },
    ArrowDown:  { axis: 1, direction: -1 },
    Numpad4:    { axis: 0, direction: -1 },
    Numpad6:    { axis: 0, direction: +1 },
    Numpad8:    { axis: 1, direction: +1 },
    Numpad2:    { axis: 1, direction: -1 },

    PageUp:     { axis: 2, direction: +1 }, // Move towards camera (Z up)
    PageDown:   { axis: 2, direction: -1 }, // Move away from camera (Z down)
    Numpad9:    { axis: 2, direction: +1 },
    Numpad3:    { axis: 2, direction: -1 },
  }
})

const SCROLL_KEYS = new Set([
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'PageUp', 'PageDown', 'Space', 'Home', 'End',
  'Numpad8', 'Numpad2', 'Numpad4', 'Numpad6', 'Numpad9', 'Numpad3',
])

// --- Props ---
const props = withDefaults(
    defineProps<{
      applyWorkingOffset?: boolean
      // Whether this viewer is the one currently on screen. A single
      // instance is shared (via Teleport, see App.vue) between the
      // Dashboard and Jogging views instead of each view owning its
      // own WebGL context — ``active`` lets the RAF render loop pause
      // while the instance is parked off-route rather than tearing
      // down and rebuilding the whole Three.js scene on every nav
      // click. Defaults to ``true`` so any other/standalone usage
      // behaves exactly as before.
      active?: boolean
    }>(),
    { applyWorkingOffset: true, active: true }
)

const store = useMachineStore()
const baseThreadStore = useBaseThreadStore()
const { progress: baseThreadProgress, axes: baseThreadAxes } = storeToRefs(baseThreadStore)

const COLOR_CUT_R = 0xf4 / 255
const COLOR_CUT_G = 0x72 / 255
const COLOR_CUT_B = 0xb6 / 255
const COLOR_PENDING_R = 0x60 / 255
const COLOR_PENDING_G = 0xa5 / 255
const COLOR_PENDING_B = 0xfa / 255

const motionLine = computed<number>(() => {
  const n = Number(baseThreadProgress.value?.motionLine ?? -1);
  return Number.isFinite(n) && n >= 0 ? Math.floor(n) : -1;
});

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

// Render-on-demand: the WebGL canvas is only redrawn when something
// actually changed (camera moved/damping settling, toolhead moved,
// toolpath/limits rebuilt, a camera-mode tween in flight, or a
// resize) instead of unconditionally every animation frame. This is
// the standard Three.js "render on demand" pattern — see
// OrbitControls' own docs — and it is the single biggest win on a
// GPU-less target: most of the time this viewer is on screen,
// nothing is moving, so the RAF loop below does almost no work.
let needsRender = true
function requestRender(): void {
  needsRender = true
}

const { quality: renderQuality, toggleQuality: toggleRenderQuality, rendererOptions, pixelRatioFor } = useRenderQuality()

const machineLimits = ref<MachineLimits | null>(null)
const toolpathMeta = ref<ToolpathMeta>({ filename: '', moves: 0 })

let lastLoadedFilename = ''
const parsedCache = new Map<string, ParsedSegment[]>()

// --- Coordinate-system helpers ---
const formatOffset = (axis: number[] | null | undefined): string => {
  if (!Array.isArray(axis) || axis.length < 3) return '0,0,0'
  const fmt = (n: number) => (Number.isFinite(n) ? n.toFixed(2) : '0')
  return `${fmt(axis[0])},${fmt(axis[1])},${fmt(axis[2])}`
}

const activeWcsIdx = computed<number>(() => {
  const n = Number(store.status.g5xIndex)
  if (!Number.isFinite(n) || n < 1 || n > 9) return 1
  return Math.floor(n)
})

const activeWcsName = computed(() => {
  const sys = WORK_COORDINATE_SYSTEMS.find((s) => s.index === activeWcsIdx.value)
  return sys ? sys.name : 'G54'
})

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

// --- Custom macro buttons (viewer.1 / viewer.2 / viewer.3) ---
//
// Same ``'axis'`` module id as ``DroPanel.vue`` so the operator
// configures every dashboard macro button from the same settings
// file; the slot id disambiguates between the DRO's per-axis rows
// and the viewer's three slots. ``MacroButton`` itself enforces
// the visibility contract (missing / disabled / empty rows render
// nothing) so we just hand the descriptor down.
const buttonConfig = useMacroButtonConfig('axis')
const { buttonsBySlot } = buttonConfig

// --- Camera-mode & jog state ---
const { defaultJogVelocity } = storeToRefs(store)
const cameraMode = ref<CameraMode>('default')
const isFocused = ref(false)
const sliderPos = ref(2)
const sliderTouched = ref(false)
const activeJogAxes = ref<Set<number>>(new Set())
const keysHeldForJog = ref<Set<string>>(new Set())

watch(defaultJogVelocity, (velocity) => {
  if (sliderTouched.value || !Number.isFinite(velocity) || velocity <= 0) return
  sliderPos.value = Math.min(MAX_JOG_SPEED, Math.max(-1, Math.log10(velocity)))
}, { immediate: true })

const jogSpeed = computed(() => Math.pow(10, sliderPos.value))

const isPlanarView = computed(() =>
  cameraMode.value === 'top' ||
  cameraMode.value === 'front' ||
  cameraMode.value === 'side',
)

const cameraModes: ReadonlyArray<{ id: CameraMode; label: string }> = [
  { id: 'default', label: 'Default' },
  { id: 'top',     label: 'Top' },
  { id: 'front',   label: 'Front' },
  { id: 'side',    label: 'Side' },
  { id: 'free',    label: 'Free' },
]

interface JogPadBinding {
  edge: 'top' | 'bottom' | 'left' | 'right'
  glyph: string
  label: string
  axis: number
  direction: number
}

const jogPadBindings = computed<JogPadBinding[]>(() => {
  switch (cameraMode.value) {
    case 'top':
      return [
        { edge: 'top',    glyph: '▲', label: 'Y+', axis: 1, direction: +1 },
        { edge: 'left',   glyph: '◀', label: 'X-', axis: 0, direction: -1 },
        { edge: 'right',  glyph: '▶', label: 'X+', axis: 0, direction: +1 },
        { edge: 'bottom', glyph: '▼', label: 'Y-', axis: 1, direction: -1 },
      ]
    case 'front':
      return [
        { edge: 'top',    glyph: '▲', label: 'Z+', axis: 2, direction: +1 },
        { edge: 'left',   glyph: '◀', label: 'X-', axis: 0, direction: -1 },
        { edge: 'right',  glyph: '▶', label: 'X+', axis: 0, direction: +1 },
        { edge: 'bottom', glyph: '▼', label: 'Z-', axis: 2, direction: -1 },
      ]
    case 'side':
      return [
        { edge: 'top',    glyph: '▲', label: 'Z+', axis: 2, direction: +1 },
        { edge: 'left',   glyph: '◀', label: 'Y-', axis: 1, direction: -1 },
        { edge: 'right',  glyph: '▶', label: 'Y+', axis: 1, direction: +1 },
        { edge: 'bottom', glyph: '▼', label: 'Z-', axis: 2, direction: -1 },
      ]
    default:
      return []
  }
})

interface CameraTween {
  startTime: number
  duration: number
  fromPos: THREE.Vector3
  toPos: THREE.Vector3
  fromTarget: THREE.Vector3
  toTarget: THREE.Vector3
}
let cameraTween: CameraTween | null = null

onMounted(async () => {
  initThreeJS()
  setupWatchers()
  if (props.active) animate()

  if (typeof store.status.file === 'string' && store.status.file.length > 0) {
    await loadProgramToolpath(store.status.file)
  }

  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('keyup', handleKeyUp)
  window.addEventListener('blur', handleWindowBlur)

  // Hydrate the macro-button config so the three viewer slots
  // resolve their descriptors (or render nothing if the operator
  // hasn't configured them yet). The composable coerces a missing
  // / corrupt payload to ``[]`` so a transient settings failure
  // never breaks the viewer.
  void buttonConfig.refresh()
})

onBeforeUnmount(() => {
  if (animationFrameId) cancelAnimationFrame(animationFrameId)
  if (resizeObserver && container.value) resizeObserver.unobserve(container.value)
  if (renderer) renderer.dispose()

  if (scene) {
    scene.traverse((object: THREE.Object3D) => {
      const mesh = object as THREE.Mesh
      if (!mesh.isMesh && !(object instanceof THREE.Line) && !(object instanceof THREE.LineSegments)) return
      if (mesh.geometry) mesh.geometry.dispose()
      if (mesh.material) {
        if (Array.isArray(mesh.material)) mesh.material.forEach(cleanMaterial)
        else cleanMaterial(mesh.material)
      }
    })
  }

  if (controls) {
    controls.removeEventListener('change', requestRender)
    controls.dispose()
  }

  cameraTween = null
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('keyup', handleKeyUp)
  window.removeEventListener('blur', handleWindowBlur)
  isFocused.value = false
  stopAllJogging()
})

const cleanMaterial = (material: THREE.Material) => {
  material.dispose()
  for (const key of Object.keys(material)) {
    const value = (material as unknown as Record<string, unknown>)[key]
    if (value && typeof value === 'object' && 'minFilter' in value && 'dispose' in value) {
      (value as unknown as { dispose: () => void }).dispose()
    }
  }
}

const initThreeJS = () => {
  if (!container.value) return

  const width = container.value.clientWidth
  const height = container.value.clientHeight

  scene = new THREE.Scene()
  scene.background = new THREE.Color('#1f2937')

  const cncSpace = new THREE.Group()
  cncSpace.rotation.x = -Math.PI / 2
  scene.add(cncSpace)

  const initialFrame = cameraFrameFor(cameraMode.value, cameraDistance.value)

  camera = new THREE.PerspectiveCamera(45, width / height, 1, 10000)
  camera.position.set(200, 200, 200)
  camera.lookAt(0, 0, 0)

  renderer = new THREE.WebGLRenderer(rendererOptions())
  renderer.setSize(width, height)
  renderer.setPixelRatio(pixelRatioFor(window.devicePixelRatio))
  container.value.appendChild(renderer.domElement)

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.05
  // Damping keeps animating the camera for a bit after the operator
  // releases the mouse/touch; ``change`` fires on every one of those
  // steps (and on every direct drag/zoom/pan), which is exactly the
  // signal the render-on-demand loop needs.
  controls.addEventListener('change', requestRender)

  controls.enableRotate = initialFrame.enableRotate

  // Three.js OrbitControls hardcodes ``touch-action: none`` on the
  // canvas in its constructor to swallow page scroll. Override it
  // here so vertical pan reaches the page scroller in every mode
  // that doesn't need the full touch surface. ``Free`` mode
  // re-applies ``none`` via ``setCameraMode`` so OrbitControls
  // owns single-finger rotation. ``touch-action`` is not
  // inherited, so writing it on a parent element wouldn't help —
  // it has to go on the canvas itself.
  renderer.domElement.style.touchAction = 'pan-y'

  const axesHelper = new THREE.AxesHelper(100)
  cncSpace.add(axesHelper)

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

  limitsGroup = new THREE.Group()
  cncSpace.add(limitsGroup)

  wcsMarkerGroup = new THREE.Group()
  cncSpace.add(wcsMarkerGroup)

  resizeObserver = new ResizeObserver(entries => {
    if (!renderer || !camera) return
    for (const entry of entries) {
      const newWidth = entry.contentRect.width
      const newHeight = entry.contentRect.height
      renderer.setSize(newWidth, newHeight)
      camera.aspect = newWidth / newHeight
      camera.updateProjectionMatrix()
    }
    requestRender()
  })
  resizeObserver.observe(container.value)
}

const updateToolheadPosition = () => {
  if (!toolheadGroup || !store.status.position) return
  const [x, y, z] = store.status.position
  toolheadGroup.position.set(x, y, z)
  requestRender()
}

const setupWatchers = () => {
  watch(() => store.status.position, updateToolheadPosition, { deep: true })
  watch(() => store.status.file, async (newFile) => {
    if (typeof newFile === 'string' && newFile.length > 0) await loadProgramToolpath(newFile)
    else clearToolpath()
  })
  watch(() => baseThreadProgress.value?.motionLine, () => {
    if (lastLoadedFilename) redrawToolpath()
  })
  watch(
      () => [store.status.g5xIndex, store.status.g5xOffset?.slice(0, 3), store.status.g92Offset?.slice(0, 3)],
      () => { if (lastLoadedFilename) redrawToolpath() },
      { deep: true },
  )
  watch(() => axisLimits.value, setMachineLimits, { immediate: true })
}

const axisLimits = computed<MachineLimits | null>(() => {
  const axes = baseThreadAxes.value || {}
  const x = axes['x']
  const y = axes['y']
  if (!x || !y) return null
  const xMin = Number(x.minLimit)
  const xMax = Number(x.maxLimit)
  const yMin = Number(y.minLimit)
  const yMax = Number(y.maxLimit)
  if (!Number.isFinite(xMin) || !Number.isFinite(xMax)) return null
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) return null
  if (xMax <= xMin || yMax <= yMin) return null
  return { xMin, xMax, yMin, yMax }
})

// ---------------------------------------------------------------------- //
// Camera view modes                                                       //
// ---------------------------------------------------------------------- //

const cameraDistance = computed<number>(() => {
  const lim = axisLimits.value
  if (!lim) return 600
  const span = Math.max(lim.xMax - lim.xMin, lim.yMax - lim.yMin)
  return Math.max(600, span * 1.4)
})

const cameraFrameFor = (mode: CameraMode, distance: number): {
  pos: THREE.Vector3
  up: THREE.Vector3
  enableRotate: boolean
} => {
  switch (mode) {
    case 'top':
      return {
        pos: new THREE.Vector3(0, distance, 0),
        up: new THREE.Vector3(0, 0, -1),
        enableRotate: false,
      }
    case 'front':
      // CNC +Y is depth. Camera at +distance looks back at -Z (CNC +Y).
      return {
        pos: new THREE.Vector3(0, 0, distance),
        up: new THREE.Vector3(0, 1, 0),
        enableRotate: false,
      }
    case 'side':
      // CNC +X is right. Camera at +distance looks back at -X (CNC -X).
      // This correctly puts +Y (CNC depth) to the right side of the screen.
      return {
        pos: new THREE.Vector3(distance, 0, 0),
        up: new THREE.Vector3(0, 1, 0),
        enableRotate: false,
      }
    case 'free':
      return {
        pos: new THREE.Vector3(200, 200, 200),
        up: new THREE.Vector3(0, 1, 0),
        enableRotate: true,
      }
    case 'default':
    default:
      return {
        pos: new THREE.Vector3(200, 200, 200),
        up: new THREE.Vector3(0, 1, 0),
        enableRotate: false,
      }
  }
}

const easeInOutCubic = (t: number): number =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2

const setCameraMode = (mode: CameraMode) => {
  if (!camera || !controls) return
  cameraMode.value = mode
  const frame = cameraFrameFor(mode, cameraDistance.value)
  camera.up.copy(frame.up)
  controls.enableRotate = frame.enableRotate
  // Re-apply the touch-action override here too so ``Free`` mode
  // can flip the canvas back to OrbitControls' hardcoded ``none``
  // (single-finger rotates the camera) without re-instantiating
  // the controls. ``initThreeJS`` does the initial write so the
  // first paint already has the right value.
  if (renderer) {
    renderer.domElement.style.touchAction = mode === 'free' ? 'none' : 'pan-y'
  }
  cameraTween = {
    startTime: performance.now(),
    duration: 400,
    fromPos: camera.position.clone(),
    toPos: frame.pos,
    fromTarget: controls.target.clone(),
    toTarget: new THREE.Vector3(0, 0, 0),
  }
  requestRender()
}

const advanceCameraTween = () => {
  if (!cameraTween || !camera || !controls) return
  const elapsed = performance.now() - cameraTween.startTime
  const t = Math.min(1, elapsed / cameraTween.duration)
  const eased = easeInOutCubic(t)
  camera.position.lerpVectors(cameraTween.fromPos, cameraTween.toPos, eased)
  controls.target.lerpVectors(cameraTween.fromTarget, cameraTween.toTarget, eased)
  camera.lookAt(controls.target)
  if (t >= 1) {
    cameraTween = null
    controls.update()
  }
}

// ---------------------------------------------------------------------- //
// Jog controls (on-screen pad + keyboard hotkeys)                         //
// ---------------------------------------------------------------------- //

const jogStart = (axis: number, direction: number) => {
  if (!isFocused.value && !jogPadBindings.value.some(b => b.axis === axis)) return
  const velocity = direction * jogSpeed.value
  activeJogAxes.value = new Set([...activeJogAxes.value, axis])
  void store.jogContinuous(axis, velocity)
}

const jogStop = (axis: number) => {
  if (!activeJogAxes.value.has(axis)) return
  const next = new Set(activeJogAxes.value)
  next.delete(axis)
  activeJogAxes.value = next
  void store.jogStop(axis)
}

const stopAllJogging = () => {
  const axes = Array.from(activeJogAxes.value)
  activeJogAxes.value = new Set()
  keysHeldForJog.value = new Set()
  for (const axis of axes) void store.jogStop(axis)
}

const isTypingInField = (): boolean => {
  if (typeof document === 'undefined') return false
  const element = document.activeElement as HTMLElement
  if (!element) return false

  if (element.tagName === 'INPUT') {
    const type = (element as HTMLInputElement).type
    if (type === 'range' || type === 'checkbox' || type === 'radio') {
      return false
    }
    return true
  }

  return element.tagName === 'TEXTAREA' || element.isContentEditable
}

const handleKeyDown = (event: KeyboardEvent) => {
  if (isTypingInField()) return
  if (!isFocused.value) return

  if (event.code === 'NumpadAdd' || event.key === '+') {
    event.preventDefault()
    sliderTouched.value = true
    sliderPos.value = Math.min(MAX_JOG_SPEED, sliderPos.value + 0.1)
    return
  }
  if (event.code === 'NumpadSubtract' || event.key === '-') {
    event.preventDefault()
    sliderTouched.value = true
    sliderPos.value = Math.max(-1, sliderPos.value - 0.1)
    return
  }

  if (SCROLL_KEYS.has(event.code)) event.preventDefault()
  if (event.repeat) return

  const binding = activeKeyBindings.value[event.code]
  if (!binding) return

  event.preventDefault()
  keysHeldForJog.value = new Set([...keysHeldForJog.value, event.code])
  jogStart(binding.axis, binding.direction)
}

const handleKeyUp = (event: KeyboardEvent) => {
  if (!keysHeldForJog.value.has(event.code)) return
  const next = new Set(keysHeldForJog.value)
  next.delete(event.code)
  keysHeldForJog.value = next

  const binding = activeKeyBindings.value[event.code]
  if (!binding) return
  event.preventDefault()
  jogStop(binding.axis)
}

const handleWindowBlur = () => stopAllJogging()

const onFocusOut = (event: FocusEvent) => {
  const containerEl = container.value?.parentElement
  if (containerEl && !containerEl.contains(event.relatedTarget as Node | null)) {
    isFocused.value = false
    stopAllJogging()
  }
}

// ---------------------------------------------------------------------- //
// Machine limits box & Custom Rectangular Grid                           //
// ---------------------------------------------------------------------- //

const setMachineLimits = (limits: MachineLimits | null) => {
  machineLimits.value = limits
  requestRender()
  if (!limitsGroup) return

  while (limitsGroup.children.length) {
    const child = limitsGroup.children.pop() as THREE.Mesh | THREE.LineSegments
    if (child.geometry) child.geometry.dispose()
    if (child.material) {
      if (Array.isArray(child.material)) child.material.forEach((m: THREE.Material) => m.dispose())
      else child.material.dispose()
    }
  }

  if (!limits) return

  const { xMin, xMax, yMin, yMax } = limits
  const OUTLINE_Z = 0.1
  const outlineGeom = new THREE.BufferGeometry()
  outlineGeom.setAttribute(
      'position',
      new THREE.Float32BufferAttribute([xMin, yMin, OUTLINE_Z, xMax, yMin, OUTLINE_Z, xMax, yMax, OUTLINE_Z, xMin, yMax, OUTLINE_Z], 3),
  )
  const outlineMat = new THREE.LineBasicMaterial({ color: 0xef4444 })
  const outline = new THREE.LineLoop(outlineGeom, outlineMat)
  limitsGroup.add(outline)

  const GRID_Z = 0.05
  const xSize = Math.max(xMax - xMin, 1)
  const ySize = Math.max(yMax - yMin, 1)
  const xDivisions = Math.max(1, Math.ceil(xSize / 10))
  const yDivisions = Math.max(1, Math.ceil(ySize / 10))
  const gridPoints: THREE.Vector3[] = []
  const stepX = xSize / xDivisions
  const stepY = ySize / yDivisions

  for (let i = 0; i <= xDivisions; i++) {
    const x = xMin + (i * stepX)
    gridPoints.push(new THREE.Vector3(x, yMin, GRID_Z))
    gridPoints.push(new THREE.Vector3(x, yMax, GRID_Z))
  }
  for (let j = 0; j <= yDivisions; j++) {
    const y = yMin + (j * stepY)
    gridPoints.push(new THREE.Vector3(xMin, y, GRID_Z))
    gridPoints.push(new THREE.Vector3(xMax, y, GRID_Z))
  }

  const gridGeometry = new THREE.BufferGeometry().setFromPoints(gridPoints)
  const gridMaterial = new THREE.LineBasicMaterial({ color: 0x334155, depthWrite: false })
  const grid = new THREE.LineSegments(gridGeometry, gridMaterial)
  limitsGroup.add(grid)
}

const loadProgramToolpath = async (filename: string) => {
  if (!scene || !filename) return
  const basename = String(filename).split(/[\\/]/).pop()
  if (!basename) return

  if (!parsedCache.has(basename)) {
    try {
      const text = await ProgramFilesService.readFile(basename)
      if (typeof text !== 'string') return clearToolpath()
      const parsed = parseGcodeToolpath(text)
      parsedCache.set(basename, parsed)
    } catch (err) {
      return clearToolpath()
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

const replaceToolpathMesh = (segments: ParsedSegment[], motion: number = motionLine.value) => {
  clearToolpathMesh()

  const activeIdx = activeWcsIdx.value
  const runtimeG5x = props.applyWorkingOffset ? activeWcsOffset.value : [0, 0, 0]
  const runtimeG92 = props.applyWorkingOffset ? liveG92.value : [0, 0, 0]

  const flat = new Float32Array(segments.length * 6)
  const colors = new Float32Array(segments.length * 6)
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    const isCut = motion > 0 && seg.sourceLine < motion
    const r = isCut ? COLOR_CUT_R : COLOR_PENDING_R
    const g = isCut ? COLOR_CUT_G : COLOR_PENDING_G
    const b = isCut ? COLOR_CUT_B : COLOR_PENDING_B

    let g5xX = 0, g5xY = 0, g5xZ = 0
    if (seg.wcsIndex === activeIdx) {
      g5xX = runtimeG5x[0]
      g5xY = runtimeG5x[1]
      g5xZ = runtimeG5x[2]
    }

    const dx = g5xX + seg.g92[0] + runtimeG92[0]
    const dy = g5xY + seg.g92[1] + runtimeG92[1]
    const dz = g5xZ + seg.g92[2] + runtimeG92[2]

    const base = i * 6
    flat[base + 0] = seg.from[0] + dx
    flat[base + 1] = seg.from[1] + dy
    flat[base + 2] = seg.from[2] + dz
    flat[base + 3] = seg.to[0] + dx
    flat[base + 4] = seg.to[1] + dy
    flat[base + 5] = seg.to[2] + dz
    colors[base + 0] = r; colors[base + 1] = g; colors[base + 2] = b
    colors[base + 3] = r; colors[base + 4] = g; colors[base + 5] = b
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(flat, 3))
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
  const material = new THREE.LineBasicMaterial({ vertexColors: true })
  toolpathLine = new THREE.LineSegments(geometry, material)
  if (scene) scene.children[0].add(toolpathLine)
  requestRender()
}

const clearToolpathMesh = () => {
  if (!toolpathLine) return
  if (toolpathLine.geometry) toolpathLine.geometry.dispose()
  if (toolpathLine.material) {
    if (Array.isArray(toolpathLine.material)) toolpathLine.material.forEach((m: THREE.Material) => m.dispose())
    else toolpathLine.material.dispose()
  }
  if (toolpathLine.parent) toolpathLine.parent.remove(toolpathLine)
  toolpathLine = null
  requestRender()
}

const clearToolpath = () => {
  clearToolpathMesh()
  if (lastLoadedFilename) parsedCache.delete(lastLoadedFilename)
  if (wcsMarkerGroup) {
    while (wcsMarkerGroup.children.length) {
      const child = wcsMarkerGroup.children.pop() as THREE.Mesh | undefined
      if (child?.geometry) child.geometry.dispose()
      if (child?.material) {
        if (Array.isArray(child.material)) child.material.forEach((m: THREE.Material) => m.dispose())
        else child.material.dispose()
      }
    }
  }
  lastLoadedFilename = ''
  toolpathMeta.value = { filename: '', moves: 0 }
}

const WCS_MARKER_ARM_LENGTH = 12

const updateWcsMarker = () => {
  if (!wcsMarkerGroup) return
  while (wcsMarkerGroup.children.length) {
    const child = wcsMarkerGroup.children.pop() as THREE.Mesh | undefined
    if (child?.geometry) child.geometry.dispose()
    if (child?.material) {
      if (Array.isArray(child.material)) child.material.forEach((m: THREE.Material) => m.dispose())
      else child.material.dispose()
    }
  }

  if (!props.applyWorkingOffset) { requestRender(); return }
  const [ox, oy, oz] = activeWcsOffset.value
  const arms: Array<{ dx: number; dy: number; dz: number; color: number }> = [
    { dx: WCS_MARKER_ARM_LENGTH, dy: 0, dz: 0, color: 0xef4444 },
    { dx: 0, dy: WCS_MARKER_ARM_LENGTH, dz: 0, color: 0x22c55e },
    { dx: 0, dy: 0, dz: WCS_MARKER_ARM_LENGTH, color: 0x3b82f6 },
  ]

  for (const arm of arms) {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute([ox, oy, oz, ox + arm.dx, oy + arm.dy, oz + arm.dz], 3))
    const m = new THREE.LineBasicMaterial({ color: arm.color })
    wcsMarkerGroup.add(new THREE.LineSegments(g, m))
  }
  requestRender()
}

const animate = () => {
  if (!props.active) {
    // Parked off-route (see App.vue's shared-instance Teleport):
    // stop scheduling frames entirely rather than rendering an
    // invisible canvas. The ``active`` watcher below restarts the
    // loop the moment this instance is teleported back on screen.
    animationFrameId = 0
    return
  }
  animationFrameId = requestAnimationFrame(animate)
  if (cameraTween) {
    advanceCameraTween()
    needsRender = true
  }
  // ``update()`` is cheap when damping has nothing left to settle
  // (an early-out inside Three.js) and is what fires the ``change``
  // listener above while it does — call it unconditionally so a
  // still-decelerating drag keeps marking frames dirty.
  if (controls) controls.update()
  if (!needsRender) return
  needsRender = false
  if (renderer && scene && camera) renderer.render(scene, camera)
}

// Resume/suspend the RAF loop as this shared instance is handed
// between routes. Reactivating forces a fresh render immediately —
// the toolhead position, loaded program, or WCS offsets may well
// have changed while parked (the underlying stores never stop
// updating; only this viewer's own render loop was paused).
watch(() => props.active, (isActive) => {
  if (isActive) {
    requestRender()
    if (!animationFrameId) animate()
  } else if (animationFrameId) {
    cancelAnimationFrame(animationFrameId)
    animationFrameId = 0
  }
})

// The render-quality toggle can change ``pixelRatioFor`` live —
// unlike ``antialias`` (fixed at WebGL context creation), the pixel
// ratio can be updated on an existing renderer.
watch(renderQuality, () => {
  if (!renderer) return
  renderer.setPixelRatio(pixelRatioFor(window.devicePixelRatio))
  requestRender()
})
</script>

<template>
  <div
    class="w-full h-full relative overflow-hidden rounded-lg outline-none border transition-all duration-200"
    :class="isFocused ? 'border-blue-400 ring-2 ring-blue-400/30' : 'border-transparent'"
    tabindex="0"
    @focusin="isFocused = true"
    @focusout="onFocusOut"
  >
    <div ref="container" class="absolute inset-0"></div>

    <!-- UI Overlay for Viewer Info -->
    <div class="absolute top-4 right-4 flex flex-col items-end gap-1 pointer-events-none">
      <div class="bg-gray-900/80 backdrop-blur text-xs text-gray-300 px-3 py-1.5 rounded border border-gray-700 font-mono">
        <div class="font-semibold text-gray-100">Ngc Coordinate System Viewer</div>

      </div>
      <!-- Render-quality toggle. Defaults to "High" (antialias + full
           device pixel ratio) so nothing changes for anyone until they
           opt out; "Low" trades that polish for a lighter WebGL render
           on weak/GPU-less hardware. Antialiasing only applies on the
           viewer's next mount (it's fixed at WebGL context creation);
           the pixel-ratio half applies immediately. -->
      <button
        type="button"
        tabindex="-1"
        class="pointer-events-auto bg-gray-900/80 backdrop-blur text-[10px] uppercase tracking-wider text-gray-300 hover:text-white px-2 py-1 rounded border border-gray-700 font-mono"
        :title="renderQuality === 'high'
          ? 'High-quality 3D rendering. Switch to Low for weak/GPU-less hardware (takes full effect after reload).'
          : 'Reduced-quality 3D rendering for weak/GPU-less hardware. Switch back to High for full visual quality (takes full effect after reload).'"
        @click="toggleRenderQuality"
      >
        {{ renderQuality === 'high' ? '3D: High' : '3D: Low' }}
      </button>
    </div>

    <!-- Camera-mode toolbar -->
    <div class="absolute top-4 left-4 flex gap-1 bg-gray-900/80 backdrop-blur border border-gray-700 rounded-lg p-1 pointer-events-auto">
      <button
        v-for="m in cameraModes"
        :key="m.id"
        type="button"
        tabindex="-1"
        @click="setCameraMode(m.id)"
        :class="cameraMode === m.id
          ? 'bg-blue-600 text-white'
          : 'bg-gray-800 text-gray-300 hover:bg-gray-700'"
        class="px-2.5 py-1 text-xs rounded transition-colors focus:outline-none"
      >{{ m.label }}</button>
    </div>

    <!-- Direction buttons (bigger touch targets) -->
    <template v-if="isPlanarView">
      <button
        v-for="b in jogPadBindings"
        :key="b.edge"
        type="button"
        tabindex="-1"
        :title="`Jog ${b.label}`"
        :aria-label="`Jog ${b.label}`"
        :class="[
          b.edge === 'top'    ? 'absolute top-6 left-1/2 -translate-x-1/2'
          : b.edge === 'bottom' ? 'absolute bottom-6 left-1/2 -translate-x-1/2'
          : b.edge === 'left'   ? 'absolute left-6 top-1/2 -translate-y-1/2'
          :                        'absolute right-6 top-1/2 -translate-y-1/2',
          activeJogAxes.has(b.axis)
            ? 'bg-blue-600 text-white'
            : 'bg-gray-900/80 text-gray-200 hover:bg-gray-700',
        ]"
        @mousedown.prevent="jogStart(b.axis, b.direction)"
        @touchstart.prevent="jogStart(b.axis, b.direction)"
        @mouseup="jogStop(b.axis)"
        @mouseleave="jogStop(b.axis)"
        @touchend="jogStop(b.axis)"
        @touchcancel="jogStop(b.axis)"
        class="w-16 h-16 backdrop-blur border border-gray-700 rounded-lg text-2xl font-bold leading-none transition-colors touch-none select-none focus:outline-none pointer-events-auto flex items-center justify-center"
      >
        <!-- The visual glyph (▲, ▼, etc.) -->
        <span>{{ b.glyph }}</span>
        <!-- Small axis label badge so you don't have to guess -->
        <span class="absolute bottom-1 right-1 text-[9px] font-mono text-gray-400 bg-gray-900/80 rounded px-1">{{ b.label }}</span>
      </button>
    </template>

    <!-- Speed-only widget -->
    <div
      v-if="isPlanarView"
      class="absolute bottom-4 right-4 bg-gray-900/80 backdrop-blur border border-gray-700 rounded-lg px-3 py-2 pointer-events-auto"
    >
      <div class="flex items-center gap-3">
        <span class="text-[10px] text-gray-400 uppercase tracking-wider">
          Speed
        </span>
        <input
          type="range"
          min="0"
          :max="MAX_JOG_SPEED"
          step="0.001"
          tabindex="-1"
          v-model.number="sliderPos"
          @input="sliderTouched = true"
          @keydown.prevent
          class="w-28 h-1.5 bg-gray-600 rounded-lg appearance-none cursor-pointer focus:outline-none"
        />
        <span class="text-xs font-mono text-blue-300 w-16 text-right">
          {{ jogSpeed < 10 ? jogSpeed.toFixed(2) : jogSpeed.toFixed(1) }} mm/s
        </span>
      </div>
    </div>

    <!-- Macro buttons (bottom-left). Three configurable slots that
         route through the shared macros store. MacroButton renders
         nothing when the descriptor is missing / disabled / empty. -->
    <div class="absolute bottom-4 left-4 flex gap-2 pointer-events-auto">
      <MacroButton
        v-if="buttonsBySlot?.['viewer.1']"
        :descriptor="buttonsBySlot['viewer.1']"
        variant="secondary"
        size="sm"
        class="px-2 py-1 text-xs backdrop-blur bg-gray-900/80 border-gray-700"
      />
      <MacroButton
        v-if="buttonsBySlot?.['viewer.2']"
        :descriptor="buttonsBySlot['viewer.2']"
        variant="secondary"
        size="sm"
        class="px-2 py-1 text-xs backdrop-blur bg-gray-900/80 border-gray-700"
      />
      <MacroButton
        v-if="buttonsBySlot?.['viewer.3']"
        :descriptor="buttonsBySlot['viewer.3']"
        variant="secondary"
        size="sm"
        class="px-2 py-1 text-xs backdrop-blur bg-gray-900/80 border-gray-700"
      />
    </div>
  </div>
</template>

<style scoped>
input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  height: 16px;
  width: 16px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  margin-top: -5px;
}
input[type="range"]::-webkit-slider-runnable-track {
  width: 100%;
  height: 6px;
  cursor: pointer;
  background: #4b5563;
  border-radius: 3px;
}
input[type="range"]::-moz-range-thumb {
  height: 16px;
  width: 16px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: none;
}
input[type="range"]::-moz-range-track {
  width: 100%;
  height: 6px;
  cursor: pointer;
  background: #4b5563;
  border-radius: 3px;
}
</style>