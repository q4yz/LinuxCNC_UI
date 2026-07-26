<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { useMachineStore } from '../stores/machine-compat'

const store = useMachineStore()

// Template ref for the container div
const container = ref(null)

// Three.js instances
let scene, camera, renderer, controls
let toolheadGroup, toolheadMesh
let animationFrameId
let resizeObserver

onMounted(() => {
  initThreeJS()
  setupWatchers()
  animate()
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
      if (!object.isMesh) return
      
      object.geometry.dispose()
      
      if (object.material.isMaterial) {
        cleanMaterial(object.material)
      } else {
        // an array of materials
        for (const material of object.material) cleanMaterial(material)
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
  // GridHelper (Size: 500mm, Divisions: 50 -> 10mm squares)
  // GridHelper is flat on XZ by default in Three.js, but since we rotated cncSpace,
  // we need to rotate the GridHelper so it lies on the CNC XY plane.
  const gridHelper = new THREE.GridHelper(500, 50, 0x444444, 0x222222)
  gridHelper.rotation.x = Math.PI / 2
  cncSpace.add(gridHelper)

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
        WebGl Viewer
      </div>
    </div>
  </div>
</template>