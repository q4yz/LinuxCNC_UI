// Frontend module registry.
//
// Discovers, filters, and registers pluggable modules under
// ``src/modules/*/index.js``. The registry is the single source of
// truth that ``App.vue`` and the sidebar consume — when no modules
// are mounted, the static navigation list stays in effect.
//
// Discovery rules (MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1):
//
//   * ``import.meta.glob`` MUST be lazy (``eager: false``). Eager
//     imports pull every module's JS into the bundle even when the
//     module is disabled by the ``MODULES_ENABLED`` whitelist, which
//     is the original bug that motivated Phase 2b.
//
//   * The whitelist filter is a soft-name filter — unknown entries
//     produce a dev-only console warning rather than aborting the
//     build. Empty / unset ``MODULES_ENABLED`` mounts everything
//     discovered (matches the backend registry).
//
// The registry boots **synchronously at import time** so the rest of
// the app can read ``registry.modules`` immediately. Module
// ``onLoad`` hooks still run synchronously inside the same import
// because they are expected to be cheap wiring code; long-running
// I/O must be scheduled by the module itself.

import { reactive } from "vue";
import { eventBus } from "./event-bus";
import { telemetryBus } from "./telemetry-bus";
import { createModuleSettings } from "./settings";

// Vite glob — ``eager: false`` is mandatory. The path is relative to
// this file (``frontend/src/core/modules/``) and intentionally fixed
// so contributors don't accidentally widen the discovery surface.
// ``{ import: 'default' }`` returns each module's default export, so
// authors write ``export default { manifest, onLoad, ... }``.
//
// The glob resolves to ``frontend/src/modules/<id>/index.js``. Note
// the **two** ``..`` segments: registry.js lives at
// ``frontend/src/core/modules/`` so a single ``..`` would land in
// ``frontend/src/core/`` (wrong folder). DashboardView lives at
// ``frontend/src/views/`` so it gets away with one ``..``; copying
// that pattern here silently breaks discovery — this comment is
// the tripwire.
//
// We deliberately keep the import path shape narrow: a module is
// either a folder with an ``index.js`` or it doesn't exist.
//
// NOTE: Vite's glob does not match the empty case. When
// ``frontend/src/modules/`` is empty (or deleted) this resolves to
// ``{}`` and the registry boots cleanly with zero modules.
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
   * @returns {Array<{id: string, title: string}>} Settings panels
   *   contributed by modules, in registry order.
   */
  settingsPanels() {
    const panels = [];
    for (const record of this.modules.values()) {
      if (record.manifest.settingsPanel) {
        panels.push({ id: record.manifest.id, title: record.manifest.title });
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