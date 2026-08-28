import { createRouter, createWebHashHistory } from 'vue-router'

import DashboardView from '../views/DashboardView.vue'
import FilesView from '../views/FilesView.vue'
import EditorView from '../views/EditorView.vue'
import SettingsView from '../views/SettingsView.vue'
import MachineConfigView from '../views/MachineConfigView.vue'
import CameraViewer from '../components/camera/CameraViewer.vue'
import JoggingView from "../views/JoggingView.vue";
import RunningView from "../views/RunningView.vue";

const BUILTIN_ROUTES = [
  {path: '/', name: 'dashboard', component: DashboardView, meta: { label: 'Dashboard' },},
  {path: '/programs', name: 'programs', component: FilesView, meta: { label: 'G-Code Files' },},
  {path: '/jogging', name: 'jogging', component: JoggingView, meta: { label: 'G-Code Files' },},
  {path: '/running', name: 'running', component: RunningView, meta: { label: 'G-Code Files' },},
  {path: '/editor', name: 'editor', component: EditorView, meta: { label: 'Editor' },},
  {path: '/settings', name: 'settings', component: SettingsView, meta: { label: 'Settings' },},
  {path: '/camera', name: 'camera', component: CameraViewer, meta: { label: 'Camera' },},
  {path: '/machineconfig', name: 'machineconfig', component: MachineConfigView, meta: { label: 'Machine Config' },},
];

const router = createRouter({
  history: createWebHashHistory(),
  routes: BUILTIN_ROUTES,
});

export default router;