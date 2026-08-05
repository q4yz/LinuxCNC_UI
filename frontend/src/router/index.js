import { createRouter, createWebHashHistory } from 'vue-router'

import DashboardView from '../views/DashboardView.vue'
import FilesView from '../views/FilesView.vue'
import EditorView from '../views/EditorView.vue'
import SettingsView from '../views/SettingsView.vue'
import MacroEditor from '../views/MacroEditor.vue'

// Hash history keeps the router compatible with static hosting
// (Vite preview / production builds served from any path).
// ``createWebHistory`` would also work if the backend always
// serves ``/index.html`` for unknown paths.
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: DashboardView,
      meta: { label: 'Dashboard' }
    },
    {
      // Route name ``programs`` matches the backend router prefix
      // (``/api/v1/programs``). The URL path stays ``/files`` for
      // user-facing consistency.
      path: '/files',
      name: 'programs',
      component: FilesView,
      meta: { label: 'G-Code Files' }
    },
    {
      // Deep-link into the editor for a specific G-code file.
      // The ``(.*)`` regex makes the segment catch-all — a path
      // like ``subfolder/file.gcode`` is captured as a single
      // ``filename`` param instead of being matched against the
      // next route segment.
      path: '/files/:filename(.*)',
      name: 'programs-file',
      component: EditorView,
      meta: { label: 'Editor' }
    },
    {
      // Single route covers both the dashboard layout
      // (``/config`` — no filename) and the per-file editor
      // (``/config/machine/axis.cfg`` — filename set). The
      // trailing ``?`` on the segment makes the parameter
      // optional; ``EditorView`` branches on
      // ``route.params.filename`` to render one or the other.
      path: '/config/:filename(.*)?',
      name: 'config',
      component: EditorView,
      meta: { label: 'Editor' }
    },
    {
      // Issue #7: dedicated macro editor view. Mirrors the
      // ``/config`` route's "filename optional" pattern so the
      // editor degrades gracefully when no macro is selected.
      path: '/macros',
      name: 'macros',
      component: MacroEditor,
      meta: { label: 'Macros' }
    },
    {
      path: '/settings',
      name: 'settings',
      component: SettingsView,
      meta: { label: 'Settings' }
    }
  ]
})

export default router
