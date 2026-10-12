import { createRouter, createWebHashHistory } from 'vue-router'

import DashboardView from '../views/DashboardView.vue'
import FilesView from '../views/FilesView.vue'
import CameraViewer from '../components/camera/CameraViewer.vue'
import JoggingView from "../views/JoggingView.vue";
import RunningView from "../views/RunningView.vue";

// Rarely-opened / heavy views load on demand: keeps the main bundle
// under the PWA's 2 MiB precache limit per file.
const EditorView = () => import('../views/EditorView.vue')
const SettingsView = () => import('../views/SettingsView.vue')
const VisualHalEditor = () => import('../views/VisualHalEditor.vue')
const ConfigView = () => import('../views/ConfigView.vue')
const DebugView = () => import('../views/DebugView.vue')
const ProbingView = () => import('../views/ProbingView.vue')

const BUILTIN_ROUTES = [
  {path: '/', name: 'dashboard', component: DashboardView, meta: { label: 'Dashboard' },},
  {path: '/programs', name: 'programs', component: FilesView, meta: { label: 'G-Code Files' },},
  {path: '/jogging', name: 'jogging', component: JoggingView, meta: { label: 'G-Code Files' },},
  {path: '/running', name: 'running', component: RunningView, meta: { label: 'G-Code Files' },},
  {path: '/probing', name: 'probing', component: ProbingView, meta: { label: 'Probing' },},
  {path: '/editor', name: 'editor', component: EditorView, meta: { label: 'Editor' },},
  {path: '/settings', name: 'settings', component: SettingsView, meta: { label: 'Settings' },},
  {path: '/camera', name: 'camera', component: CameraViewer, meta: { label: 'Camera' },},
  {path: '/hal-editor', name: 'hal-editor', component: VisualHalEditor, meta: { label: 'HAL Editor' },},
  {path: '/config', name: 'config', component: ConfigView, meta: { label: 'Config' },},
  {path: '/debug', name: 'debug', component: DebugView, meta: { label: 'Debug' },},
];

const router = createRouter({
  history: createWebHashHistory(),
  routes: BUILTIN_ROUTES,
});

export default router;