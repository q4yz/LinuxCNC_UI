// Frontend module registry. Discovers, filters, and mounts modules
// under ``src/modules/*/index.js``. See ``.agent/STATE.md`` § 1, § 7
// for the discovery and nullable-module rules.

import { reactive } from "vue";
import { eventBus } from "./event-bus";
import { telemetryBus } from "./telemetry-bus";
import { createModuleSettings } from "./settings";

// ``eager: false`` is mandatory — see ``.agent/STATE.md`` § 1.
// Path uses two ``..`` segments: this file is in
// ``frontend/src/core/modules/`` (one segment up would land in
// ``frontend/src/core/``). Don't copy the one-segment path from
// ``DashboardView.vue``.
const moduleImports = import.meta.glob(
  "../../modules/*/index.js",
  { eager: false },
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
   */
  async boot() {
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
    // module id (``/modules/<id>/index.js``).
    const candidates = Object.entries(moduleImports);
    const byId = new Map();
    for (const [path, importer] of candidates) {
      const mod = await importer();
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
    try {
      const result = instance.onLoad?.(ctx);
      if (result && typeof result.then === "function") {
        // eslint-disable-next-line no-console
        console.warn(
          `[registry] module '${id}' returned a Promise from onLoad(); awaiting it is not supported`,
        );
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(`[registry] module '${id}' onLoad threw:`, err);
      return;
    }
    this.modules.set(id, {
      manifest: instance.manifest,
      context: ctx,
      sidebar: instance.sidebar ?? instance.manifest.sidebar ?? null,
      // Module-supplied settings-tab component. Optional — modules
      // without one still get a tab via ``settingsPanels()`` so the
      // legacy placeholder keeps working.
      settingsPanel: instance.settingsPanel ?? null,
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