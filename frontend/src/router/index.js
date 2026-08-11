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
//      also a Vue Router name.
//
//   2. Module-sidebar ids (``camera``, ``machineconfig``, ...) are
//      registered at runtime by ``registerModuleRoutes`` after
//      ``registry.boot()`` resolves — see ``main.js``. Mounting
//      module routes lazily keeps the registry's ``MODULES_ENABLED``
//      whitelist authoritative: a module excluded by the env var
//      never produces a route at all.
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
 * Built-in route names (``dashboard``, ``programs``, ``editor``,
 * ``settings``) win over module-supplied routes with the same
 * name. Modules whose manifest id collides with a built-in are
 * skipped — they get the built-in editor / settings surface
 * instead of trying to override it.
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