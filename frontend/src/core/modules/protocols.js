// JSDoc typedefs for the frontend module surface. See
// ``.agent/contracts/frontend-module.md`` for the authoritative doc.

/**
 * @typedef {Object} SidebarEntry
 * @property {string} id    Stable identifier; must be unique app-wide.
 * @property {string} label Display text rendered in the sidebar.
 * @property {string} [icon] Optional SVG/HTML icon string.
 * @property {number} [order=100] Sort weight. Lower numbers first.
 */

/**
 * @typedef {Object} FrontendModuleManifest
 * @property {string} id     Unique module identifier (matches backend).
 * @property {string} title  Human-readable display name.
 * @property {string} [version="0.0.0"] Semantic-ish version.
 * @property {string} [description=""] One-line description.
 * @property {SidebarEntry} [sidebar] Optional sidebar entry.
 * @property {boolean} [settingsPanel=false] Whether this module contributes a Settings tab.
 * @property {boolean} [route=false] Whether this module exposes a top-level Vue route.
 * @property {import('vue').Component} [mainView]
 *   Top-level view rendered by ``App.vue`` when this module's route
 *   is active. Without it, ``App.vue`` falls back to an alphabetical
 *   glob discovery over the module's ``components/*.vue`` files
 *   (deprecated; new modules should always export ``mainView``).
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
 * @property {FrontendModuleManifest} manifest Static metadata.
 * @property {(ctx: ModuleContext) => void | Promise<void>} onLoad  Lifecycle hook.
 * @property {() => void} [onUnload] Optional teardown hook.
 * @property {SidebarEntry} [sidebar] Optional sidebar entry (mirrors manifest.sidebar).
 * @property {import('vue').Component} [settingsPanel] Optional settings-tab component
 *   rendered inside the Settings view when ``manifest.settingsPanel`` is
 *   true. The component is mounted with no props — modules must
 *   consume the registry's settings client / Pinia store directly.
 * @property {import('vue').Component} [mainView]
 *   Top-level view mounted by ``App.vue`` when the route name
 *   matches the module's ``manifest.id`` or ``manifest.sidebar.id``.
 *   Replaces the old alphabetical glob-based discovery; new modules
 *   should always export this so the sidebar click resolves
 *   deterministically without depending on file naming.
 */

/**
 * @typedef {Object} FrontendModuleRecord
 * @property {FrontendModuleManifest} manifest The module's manifest.
 * @property {ModuleContext} context The runtime context handed to onLoad.
 * @property {SidebarEntry|null} sidebar Sidebar entry (or null).
 * @property {import('vue').Component|null} mainView
 *   The module's top-level view (mirrors ``instance.mainView``), or
 *   ``null`` when the module did not export one and ``App.vue`` is
 *   expected to fall back to the legacy glob discovery.
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
