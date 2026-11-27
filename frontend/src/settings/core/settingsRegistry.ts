// Central registry + cache for every UI setting.
//
// A plain module, not a Pinia store: settings are instantiated at import
// time (``settings/definitions``), before any app or Pinia exists.
//
//   * ``register`` — called by every ``BaseSetting`` constructor. The same
//     key may only be defined once; an identical re-definition (HMR
//     re-running a definitions module) replaces the old instance, a
//     *different* one throws — two meanings for one key is a bug.
//   * ``fetchAll`` — one GET for the whole session (memoized), cached in
//     ``rawCache``. Settings that register later still hydrate from it.
//     Desync with another client is acceptable (UI-only settings): a
//     page reload picks up their changes.
//   * ``critical`` settings never hydrate from the cache — they are read
//     fresh via ``setting.load()`` (see BaseSetting).
//   * ``categories`` — settings grouped for the generated Settings view.
//   * Per-login values: the admin's values are the shared set, everyone
//     else (viewers, the agent) sees them; a user's own overrides come on
//     top. ``personal`` lists the keys the caller set for themselves,
//     ``machineKeys`` the machine-wide keys only an admin changes. A login
//     or logout (``onTokenChange``) refetches.

import { computed, ref, shallowReactive } from "vue";
import type { BaseSetting } from "./BaseSetting";
import { settingsFacade } from "../../facades/settingsFacade";
import { describeError } from "../../core/error-format";
import { settingsLog } from "./settingsLog";
import { onTokenChange } from "../../core/authToken";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnySetting = BaseSetting<any>;

const settings = shallowReactive(new Map<string, AnySetting>());
let rawCache: Record<string, unknown> | null = null;
let fetchPromise: Promise<boolean> | null = null;
const fetched = ref(false);
const personal = ref<ReadonlySet<string>>(new Set());
const machineKeys = ref<readonly string[]>([]);

function isMachineKey(key: string): boolean {
  return machineKeys.value.some((k) => (k.endsWith(".") ? key.startsWith(k) : key === k));
}

function hydrateFromCache(setting: AnySetting): void {
  if (rawCache === null || setting.critical) return;
  setting.hydrate(Object.prototype.hasOwnProperty.call(rawCache, setting.key) ? rawCache[setting.key] : undefined);
}

function register(setting: AnySetting): void {
  const existing = settings.get(setting.key);
  if (existing && existing.signature() !== setting.signature()) {
    throw new Error(
      `Setting "${setting.key}" is defined twice with different definitions:\n` +
        `  ${existing.signature()}\n  ${setting.signature()}`,
    );
  }
  settings.set(setting.key, setting);
  hydrateFromCache(setting);
}

/** Load every stored setting once per session. Resolves ``true`` on success. */
function fetchAll(): Promise<boolean> {
  if (fetchPromise) return fetchPromise;
  fetchPromise = (async () => {
    try {
      const listing = await settingsFacade.listDetailed();
      rawCache = listing.values;
      personal.value = new Set(listing.personal);
      machineKeys.value = listing.machineKeys;
      settings.forEach(hydrateFromCache);
      fetched.value = true;
      settingsLog("debug", `Settings: loaded ${Object.keys(rawCache).length} stored value(s), ${settings.size} setting(s) defined`);
      return true;
    } catch (err: unknown) {
      // Allow a later retry; settings keep showing their defaults.
      fetchPromise = null;
      settingsLog("warning", `Settings: could not load stored values (${describeError(err)}) — showing defaults`);
      return false;
    }
  })();
  return fetchPromise;
}

/** Forget the session cache and load again (login/logout, a user's reset). */
async function refetch(): Promise<boolean> {
  if (fetchPromise) await fetchPromise.catch(() => undefined);
  fetchPromise = null;
  const ok = await fetchAll();
  // Critical settings never hydrate from the cache: re-read them too.
  if (ok) await Promise.all([...settings.values()].filter((s) => s.critical && s.isLoaded).map((s) => s.load()));
  return ok;
}

onTokenChange(() => {
  void refetch();
});

const categories = computed(() => {
  const groups: Record<string, AnySetting[]> = {};
  settings.forEach((setting) => {
    (groups[setting.category] ??= []).push(setting);
  });
  for (const list of Object.values(groups)) {
    list.sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
  }
  return groups;
});

export const settingsRegistry = Object.freeze({
  register,
  fetchAll,
  refetch,
  categories,
  fetched,
  /** The caller set this key for themselves (a user's own value). */
  isPersonal: (key: string): boolean => personal.value.has(key),
  /** Machine-wide: read by the backends, only an admin changes it. */
  isMachineKey,
  get: (key: string): AnySetting | undefined => settings.get(key),
  all: (): AnySetting[] => [...settings.values()],
  /** Test-only: forget every setting and the cache. */
  _resetForTests(): void {
    settings.clear();
    rawCache = null;
    fetchPromise = null;
    fetched.value = false;
    personal.value = new Set();
    machineKeys.value = [];
  },
});

export default settingsRegistry;
