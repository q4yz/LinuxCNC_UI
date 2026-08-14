// Frontend module registry. Discovers, filters, and mounts modules
// under ``src/modules/*/index.js``. See ``.agent/STATE.md`` § 1, § 13
// for the eager-discovery and no-lazy-imports rules.
//
// Modules are mandatory: every module that ships in
// ``frontend/src/modules/<id>/`` is a hard dependency. There is no
// "nullable" surface — ``mainView`` and ``settingsPanel`` must be
// non-null Vue components, the manifest must carry a sidebar entry,
// and the module's JS is loaded eagerly so removing the folder is a
// build failure rather than a graceful no-op.

import { markRaw, reactive } from "vue";
import { eventBus } from "./event-bus";
import { telemetryBus } from "./telemetry-bus";
import { createModuleSettings } from "./settings";

// ``eager: true`` is mandatory — see ``.agent/STATE.md`` § 13. Module
// JS ships at app start; the ``MODULES_ENABLED`` whitelist only
// controls whether ``onLoad`` runs and whether the record enters the
// registry map, not whether the code is loaded.
//
// Path uses two ``..`` segments: this file is in
// ``frontend/src/core/modules/`` (one segment up would land in
// ``frontend/src/core/``). Don't copy the one-segment path from
// ``DashboardView.vue``.
const moduleImports = import.meta.glob(
  "../../modules/*/index.js",
  { eager: true },
);

/**
 * Read the ``MODULES_ENABLED`` env var at build/dev time.
 *
 * Vite injects ``import.meta.env.VITE_*`` variables; we accept either
 * the Vite-style ``VITE_MODULES_ENABLED`` or the raw ``MODULES_ENABLED``
 * (the latter is only meaningful in dev because prod bundles the
 * value at build time).
 *
 * @returns {Set<string>|null} ``null`` means "mount everything".
 */
function parseEnabled() {
  const raw =
    import.meta.env?.VITE_MODULES_ENABLED ??
    // Fallback for non-Vite dev/test environments (jsdom, vitest).
    (typeof process !== "undefined" ? process.env?.MODULES_ENABLED : "") ??
    "";
  const value = String(raw).trim();
  if (!value) return null;
  return new Set(
    value
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
}

class FrontendRegistry {
  constructor() {
    /**
     * Vue-reactive Map. ``computed(() => registry.modules.has(id))``
     * and other consumers track Map mutations (``.set``/``.delete``/
     * ``.clear``) without needing a manual re-snapshot. Vue 3's
     * collection handlers transparently wrap ``Map``/``Set`` so
     * standard iteration (``for..of``, ``Object.keys``) keeps
     * working in tests.
     * @type {Map<string, import('./protocols').FrontendModuleRecord>}
     */
    this.modules = reactive(new Map());
    /** @type {import('./event-bus').EventBus} */
    this.eventBus = eventBus;
    /** @type {import('./telemetry-bus').TelemetryBus} */
    this.telemetryBus = telemetryBus;
    this._booted = false;
  }

  /**
   * Walk the Vite glob, filter by ``MODULES_ENABLED``, and call each
   * module's ``onLoad`` hook. Idempotent: a second ``boot()`` call
   * is a no-op so the registry can be safely imported twice (e.g.
   * by tests).
   *
   * The module's ``onLoad`` hook MUST be synchronous. Modules that
   * previously returned a Promise are no longer accepted; the
   * registry logs a warning and treats the module as failed.
   */
  boot() {
    if (this._booted) return;
    this._booted = true;

    const whitelist = parseEnabled();
    const seenIds = new Set();
    /** @type {string[]} */
    const mountedIds = [];
    /** @type {string[]} */
    const skippedIds = [];
    /** @type {string[]} */
    const missingIds = [];

    // Build the candidate list synchronously. ``moduleImports`` is
    // an object keyed by absolute path; the path itself encodes the
    // module id (``/modules/<id>/index.js``). With ``eager: true``
    // the imports have already resolved to module objects.
    const candidates = Object.entries(moduleImports);
    const byId = new Map();
    for (const [path, mod] of candidates) {
      const instance = mod.default ?? mod;
      const manifest = instance?.manifest;
      if (!manifest || !manifest.id) {
        // eslint-disable-next-line no-console
        console.warn(
          `[registry] module at ${path} has no manifest; skipping`,
        );
        continue;
      }
      if (byId.has(manifest.id)) {
        // eslint-disable-next-line no-console
        console.warn(
          `[registry] duplicate module id '${manifest.id}'; skipping ${path}`,
        );
        continue;
      }
      byId.set(manifest.id, { instance, path });
    }

    // Apply the whitelist.
    if (whitelist === null) {
      // No whitelist: mount everything we found.
      for (const [id, candidate] of byId) {
        this._mount(id, candidate);
        mountedIds.push(id);
        seenIds.add(id);
      }
    } else {
      for (const id of whitelist) {
        if (!byId.has(id)) {
          missingIds.push(id);
          // eslint-disable-next-line no-console
          console.warn(`[registry] unknown module id '${id}'`);
          continue;
        }
        this._mount(id, byId.get(id));
        mountedIds.push(id);
        seenIds.add(id);
      }
      for (const id of byId.keys()) {
        if (!seenIds.has(id)) skippedIds.push(id);
      }
    }

    // eslint-disable-next-line no-console
    console.info(
      `[registry] mounted=${mountedIds} skipped=${skippedIds.length} missing=${missingIds.length}`,
    );
  }

  /**
   * @param {string} id
   * @param {{instance: any, path: string}} candidate
   */
  _mount(id, { instance, path }) {
    const ctx = {
      id,
      eventBus: this.eventBus,
      telemetryBus: this.telemetryBus,
      settings: createModuleSettings(id),
    };
    // The contract requires a synchronous ``onLoad``. A Promise
    // return is a contract violation — the registry used to log a
    // warning and continue; it now refuses the module entirely.
    if (typeof instance.onLoad !== "function") {
      // eslint-disable-next-line no-console
      console.error(
        `[registry] module '${id}' has no onLoad function; refusing mount`,
      );
      return;
    }
    try {
      const result = instance.onLoad(ctx);
      if (result && typeof result.then === "function") {
        // eslint-disable-next-line no-console
        console.error(
          `[registry] module '${id}' returned a Promise from onLoad(); refusing mount (the contract forbids async onLoad)`,
        );
        return;
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(`[registry] module '${id}' onLoad threw:`, err);
      return;
    }
    if (typeof instance.onUnload !== "function") {
      // eslint-disable-next-line no-console
      console.error(
        `[registry] module '${id}' has no onUnload function; refusing mount`,
      );
      return;
    }
    if (!instance.mainView) {
      // eslint-disable-next-line no-console
      console.error(
        `[registry] module '${id}' is missing mainView; refusing mount`,
      );
      return;
    }
    // ``markRaw`` keeps the Vue component definitions out of the
    // reactive proxy so Vue does not warn about "Component that
    // was made a reactive object" when the registry stores them in
    // its reactive Map. The Map is reactive; the components are
    // intentionally not.
    this.modules.set(id, {
      manifest: instance.manifest,
      context: ctx,
      sidebar: instance.sidebar ?? instance.manifest.sidebar,
      settingsPanel: instance.settingsPanel
        ? markRaw(instance.settingsPanel)
        : null,
      mainView: markRaw(instance.mainView),
    });
  }

  /**
   * @returns {SidebarEntry[]} Sidebar entries contributed by modules,
   *   sorted by ``order``. Empty if no modules are mounted.
   */
  sidebarEntries() {
    const entries = [];
    for (const record of this.modules.values()) {
      if (record.sidebar) entries.push(record.sidebar);
    }
    entries.sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
    return entries;
  }

  /**
   * @returns {Array<{id: string, title: string, panel: (() => any) | null}>}
   *   Settings panels contributed by modules, in registry order.
   *   ``panel`` is a Vue component (or ``null`` when the module
   *   hasn't shipped one yet — callers fall back to the placeholder).
   */
  settingsPanels() {
    const panels = [];
    for (const record of this.modules.values()) {
      if (record.manifest.settingsPanel) {
        panels.push({
          id: record.manifest.id,
          title: record.manifest.title,
          panel: record.settingsPanel ?? null,
        });
      }
    }
    return panels;
  }

  /** Tear every module down in reverse registration order. */
  shutdown() {
    const ids = Array.from(this.modules.keys()).reverse();
    for (const id of ids) {
      const record = this.modules.get(id);
      try {
        record?.context?.onUnload?.();
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error(`[registry] module '${id}' onUnload threw:`, err);
      }
    }
    this.modules.clear();
    this._booted = false;
  }
}

// Module-level singleton. ``App.vue`` imports this and awaits the
// ``boot()`` promise during app startup.
export const registry = new FrontendRegistry();

export default registry;