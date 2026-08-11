import { createRouter, createWebHashHistory } from 'vue-router'

import DashboardView from '../views/DashboardView.vue'
import FilesView from '../views/FilesView.vue'
import EditorView from '../views/EditorView.vue'
import SettingsView from '../views/SettingsView.vue'

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
//      also a Vue Router name. ``config`` is the one built-in that
//      only exists in the router: it powers the editor deep-link
//      (``/config/...``) but no longer has a built-in sidebar entry
//      because the ``machineconfig`` module owns that slot now.
//
//   2. Module-sidebar ids (``camera``, ``machineconfig``, ...) are
//      registered at runtime by ``registerModuleRoutes`` after
//      ``registry.boot()`` resolves — see ``main.js``. Mounting
//      module routes lazily keeps the registry's ``MODULES_ENABLED``
//      whitelist authoritative: a module excluded by the env var
//      never produces a route at all.
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
    // Deep-link into the editor for a specific G-code file.
    // The ``(.*)`` regex makes the segment catch-all — a path
    // like ``subfolder/file.gcode`` is captured as a single
    // ``filename`` param instead of being matched against the
    // next route segment.
    path: '/programs/:filename(.*)',
    name: 'programs-file',
    component: EditorView,
    meta: { label: 'Editor' },
  },
  {
    // Single route covers both the machineconfig dashboard layout
    // (when the registry registers ``/machineconfig``, see below)
    // and the editor for an individual INI/CFG file. The route
    // stays under ``config`` so existing deep-links (e.g.
    // ``FileManager.vue``/``McodePanel.vue``/``McodeManagerPanel.vue``)
    // keep working unchanged. The trailing ``?`` on the segment
    // makes the parameter optional; ``EditorView`` branches on
    // ``route.params.filename`` to render one or the other.
    path: '/config/:filename(.*)?',
    name: 'config',
    component: EditorView,
    meta: { label: 'Editor' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: SettingsView,
    meta: { label: 'Settings' },
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes: BUILTIN_ROUTES,
})

/**
 * Walk the mounted module registry and add one ``/<sidebar.id>``
 * route per module whose manifest declares a sidebar entry.
 *
 * Each registered route uses ``DashboardView`` as the placeholder
 * component because the placeholder never actually renders:
 * ``App.vue`` reads ``useRoute().name`` synchronously and renders
 * the registry's ``mainView`` instead (see ``App.vue::moduleView``).
 * A bare Vue Router link / browser-bar deep link to ``/#/camera``
 * lands on the placeholder for one frame at most; in practice
 * App.vue replaces the slot before paint.
 *
 * Built-in route names (``dashboard``, ``programs``, ``programs-file``,
 * ``config``, ``settings``) win over module-supplied routes with
 * the same name. Modules whose manifest id collides with a
 * built-in are skipped — they get the built-in editor / settings
 * surface instead of trying to override it.
 *
 * @param {import('../core/modules/registry').default} registry
 *   The frontend registry after ``registry.boot()`` has resolved.
 * @returns {string[]} Names of the routes added. Useful for tests.
 */
export function registerModuleRoutes(registry) {
  if (!registry || !registry.modules) {
    return []
  }
  const builtInNames = new Set(BUILTIN_ROUTES.map((r) => r.name))
  /** @type {string[]} */
  const added = []
  for (const record of registry.modules.values()) {
    const sidebar = record.sidebar
    if (!sidebar || !sidebar.id) continue
    if (builtInNames.has(sidebar.id)) continue
    if (router.hasRoute(sidebar.id)) continue
    router.addRoute({
      path: `/${sidebar.id}`,
      name: sidebar.id,
      component: DashboardView,
      meta: { label: sidebar.label || sidebar.id },
    })
    builtInNames.add(sidebar.id)
    added.push(sidebar.id)
  }
  return added
}

export default router
