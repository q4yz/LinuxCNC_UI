// JSDoc typedefs for the frontend module surface. See
// ``.agent/contracts/frontend-module.md`` for the authoritative doc.
//
// Modules are mandatory. Every required field on the typedefs below
// must be present on a module's default export — there is no
// "optional" surface. The contract also forbids lazy imports
// (``defineAsyncComponent``, dynamic ``import()``, or
// ``import.meta.glob(..., { eager: false })``) anywhere inside the
// module surface; see ``frontend/scripts/check-no-lazy-imports.mjs``.

/**
 * @typedef {Object} SidebarEntry
 * @property {string} id    Stable identifier; must be unique app-wide.
 * @property {string} label Display text rendered in the sidebar.
 * @property {string} icon  SVG/HTML icon string. Empty string allowed.
 * @property {number} order Sort weight. Lower numbers first. Default 100.
 */

/**
 * @typedef {Object} FrontendModuleManifest
 * @property {string} id              Unique module identifier (matches backend).
 * @property {string} title           Human-readable display name.
 * @property {string} version         Semantic-ish version string. Required.
 * @property {string} description     One-line description. Empty string allowed.
 * @property {SidebarEntry} sidebar   Sidebar entry. Required (no `undefined`).
 * @property {boolean} settingsPanel  Whether this module contributes a Settings tab.
 */

/**
 * @typedef {Object} ModuleContext
 * @property {string} id               Module identifier.
 * @property {import('./event-bus').EventBus} eventBus  Cross-module pub/sub.
 * @property {import('./telemetry-bus').TelemetryBus} telemetryBus High-frequency telemetry.
 * @property {import('./settings').ModuleSettingsApi} settings  Typed settings client.
 */

/**
 * @typedef {Object} FrontendModule
 * @property {FrontendModuleManifest} manifest            Static metadata.
 * @property {(ctx: ModuleContext) => void} onLoad        Synchronous lifecycle hook.
 * @property {() => void} onUnload                       Optional-but-required teardown hook.
 * @property {SidebarEntry} sidebar                      Mirrors ``manifest.sidebar``.
 * @property {import('vue').Component} settingsPanel      Settings-tab component.
 * @property {import('vue').Component} mainView           Top-level view mounted by ``App.vue``.
 */

/**
 * @typedef {Object} FrontendModuleRecord
 * @property {FrontendModuleManifest} manifest The module's manifest.
 * @property {ModuleContext} context            The runtime context handed to onLoad.
 * @property {SidebarEntry} sidebar             Sidebar entry (always present).
 * @property {import('vue').Component} settingsPanel  Settings-tab component.
 * @property {import('vue').Component} mainView       Top-level view.
 */

/**
 * @typedef {Object} RouterRegistrarOptions
 * @property {string} [placeholderComponent] Component used as the
 *   placeholder for dynamically-registered module routes. ``App.vue``
 *   swaps in ``moduleView`` before the placeholder ever renders, so
 *   this only matters in the rare case where ``App.vue`` is not on
 *   screen. Defaults to the Dashboard view component.
 */

export {};
