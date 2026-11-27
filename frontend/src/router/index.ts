import { createRouter, createWebHashHistory } from 'vue-router'

import DashboardView from '../views/DashboardView.vue'
import FilesView from '../views/FilesView.vue'
import CameraViewer from '../components/camera/CameraViewer.vue'
import JoggingView from "../views/JoggingView.vue";
import RunningView from "../views/RunningView.vue";
import { installPermissionGuard } from "./guards/permissionGuard";

// Rarely-opened / heavy views load on demand: keeps the main bundle
// under the PWA's 2 MiB precache limit per file.
const EditorView = () => import('../views/EditorView.vue')
const SettingsView = () => import('../views/SettingsView.vue')
const VisualHalEditor = () => import('../views/VisualHalEditor.vue')
const ConfigView = () => import('../views/ConfigView.vue')
const DebugView = () => import('../views/DebugView.vue')
const CalibrationView = () => import('../views/CalibrationView.vue')

const BUILTIN_ROUTES = [
  {path: '/', name: 'dashboard', component: DashboardView, meta: { label: 'Dashboard' },},
  {path: '/programs', name: 'programs', component: FilesView, meta: { label: 'G-Code Files' },},
  {path: '/jogging', name: 'jogging', component: JoggingView, meta: { label: 'G-Code Files' },},
  {path: '/running', name: 'running', component: RunningView, meta: { label: 'G-Code Files' },},
  // probing is a Dashboard panel now (settings: Settings -> Probing)
  {path: '/probing', redirect: { name: 'dashboard' }},
  {path: '/calibration', name: 'calibration', component: CalibrationView, meta: { label: 'Calibration' },},
  // the bed mesh lives on the Calibration tab now (its Details pop-up)
  {path: '/bedmesh', redirect: { name: 'calibration' }},
  {path: '/editor', name: 'editor', component: EditorView, meta: { label: 'Editor' },},
  {path: '/settings', name: 'settings', component: SettingsView, meta: { label: 'Settings' },},
  {path: '/camera', name: 'camera', component: CameraViewer, meta: { label: 'Camera' },},
  // admins only (meta.permission: router/guards/permissionGuard.ts)
  {path: '/hal-editor', name: 'hal-editor', component: VisualHalEditor, meta: { label: 'HAL Editor', permission: 'hal.write' },},
  {path: '/config', name: 'config', component: ConfigView, meta: { label: 'Config', permission: 'config.write' },},
  {path: '/debug', name: 'debug', component: DebugView, meta: { label: 'Debug', permission: 'hal.write' },},
];

const router = createRouter({
  history: createWebHashHistory(),
  routes: BUILTIN_ROUTES,
});
installPermissionGuard(router);

export default router;