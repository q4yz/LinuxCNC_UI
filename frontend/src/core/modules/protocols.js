// Frontend module-system contracts.
//
// These types describe the surface every pluggable frontend module
// must satisfy. They mirror the backend ``PluggableModule`` Protocol
// but adapted for Vue 3 / Vite conventions. JSDoc typedefs give us
// type hints without forcing a TypeScript build step — the project is
// otherwise pure JavaScript.
//
// Authoritative docs:
//   .agent/contracts/frontend-module.md
//   .agent/contracts/settings-module.md
//   MODULE_SYSTEM_ROADMAP.md § 12 Implementation Gotchas

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
 */

/**
 * @typedef {Object} FrontendModuleRecord
 * @property {FrontendModuleManifest} manifest The module's manifest.
 * @property {ModuleContext} context The runtime context handed to onLoad.
 * @property {SidebarEntry|null} sidebar Sidebar entry (or null).
 */

export {};