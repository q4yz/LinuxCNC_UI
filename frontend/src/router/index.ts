import { createRouter, createWebHashHistory } from 'vue-router'

import DashboardView from '../views/DashboardView.vue'
import FilesView from '../views/FilesView.vue'
import EditorView from '../views/EditorView.vue'
import SettingsView from '../views/SettingsView.vue'
import MachineConfigView from '../views/MachineConfigView.vue'
import CameraViewer from '../components/camera/CameraViewer.vue'

// Hash history keeps the router compatible with static hosting
// (Vite preview / production builds served from any path).
// ``createWebHistory`` would also work if the backend always
// serves ``/index.html`` for unknown paths.
//
// Two design rules baked into this table:
//
//   1. The route **name** doubles as the sidebar id the App shell
//      uses (see ``AppSidebar.vue``). Every built-in sidebar entry
//      (``dashboard``, ``programs``, ``settings``) is therefore
//      also a Vue Router name.
//
//   2. Per-domain routes (``camera``, ``machineconfig``) live
//      here as plain literals so removing a route is a build
//      failure rather than a silent gap. The component for each
//      route is imported statically at the top of the file.
//
// Issue #132 — editor contract
// ----------------------------
// The editor is now a single route (``/editor``) whose inputs are
// passed via the URL query string:
//
//     /editor?source=profiles&name=klipper.cfg
//     /editor?source=active&name=hardware.json&readOnly=true
//     /editor?source=staged&name=machine.cfg&readOnly=true
//     /editor?source=m_codes&name=M101
//     /editor?source=programs&name=foo.gcode
//     /editor?source=macros&name=my_macro
//
// Legacy routes (``/programs/:filename`` and ``/config/:filename``)
// were removed — they encoded the routing-by-extension bug. The
// helpers in ``frontend/src/helpers/openInEditor.js`` build the new
// URLs so every caller uses the same shape.
const BUILTIN_ROUTES = [
  {
    path: '/',
    name: 'dashboard',
    component: DashboardView,
    meta: { label: 'Dashboard' },
  },
  {
    // Route name ``programs`` matches the sidebar id used by the
    // built-in G-Code Files sidebar entry. The URL path
    // (``/programs``) matches the name; the legacy ``/files`` path
    // was removed when the sidebar entries became route names.
    path: '/programs',
    name: 'programs',
    component: FilesView,
    meta: { label: 'G-Code Files' },
  },
  {
    // Universal editor route. ``source`` + ``name`` + optional
    // ``readOnly`` come from the query string; ``EditorView``
    // converts them into a ``useEditorStore`` open() call.
    path: '/editor',
    name: 'editor',
    component: EditorView,
    meta: { label: 'Editor' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: SettingsView,
    meta: { label: 'Settings' },
  },
  {
    path: '/camera',
    name: 'camera',
    component: CameraViewer,
    meta: { label: 'Camera' },
  },
  {
    path: '/machineconfig',
    name: 'machineconfig',
    component: MachineConfigView,
    meta: { label: 'Machine Config' },
  },
];

const router = createRouter({
  history: createWebHashHistory(),
  routes: BUILTIN_ROUTES,
});

export default router;