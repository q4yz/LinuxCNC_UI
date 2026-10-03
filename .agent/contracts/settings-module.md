# Contract: central UI settings

> All UI settings live in **one** key/value document served by the
> **system service** (always running, also while the machine backend
> is offline). There are no per-module settings endpoints, Pydantic
> settings models or per-module `settings.json` files any more.

## 1. Storage (system service)

- File: `backend/data/settings.json` — flat `{ "<key>": <json value> }`
  (`UI_SETTINGS_FILE` in `common/domain_file_services/paths.py`).
  Per-installation runtime data, git-ignored.
- Store: `common/core/ui_settings_store.py` (`UiSettingsStore`) — the
  only writer. Atomic write (`common/core/atomic_json.py`: temp file +
  `os.replace`), in-memory cache for the system process.
- Keys are namespaced identifiers, never paths:
  `^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$` (e.g. `camera.ip_camera_url`).
  Values: any JSON, ≤ 64 KB serialized.
- **No backend defaults.** A key that was never written is *unset*; the
  frontend definition owns the default.

## 2. HTTP API — `backend/system/routers/ui_settings.py`

| Method + path | operationId | Result |
|---|---|---|
| `GET /api/v1/settings` | `listSettings` | `{values: {key: value}}` — every stored key |
| `GET /api/v1/settings/{key}` | `readSetting` | `{key, value}`; **404** when unset |
| `PUT /api/v1/settings/{key}` body `{value}` | `writeSetting` | `{key, value}` — the echo *is* the save confirmation |
| `DELETE /api/v1/settings/{key}` | `resetSetting` | 204 — back to the frontend default (idempotent) |

Bad key / oversized value → 400. Routed to the system service by
`frontend/vite.config.mjs`, `docker/nginx.conf` and `install.sh`.

## 3. Reading a setting from Python (other processes)

`common/core/ui_settings_reader.py`:
`read_ui_setting(key, default)` — parses the file **on every call**
(no cache), so a value saved in the UI applies to the next request
without a restart. Only for settings marked **critical** in the
frontend (today: `camera.ip_camera_url`, `camera.default_device_id`,
read by the machine backend's camera supervisor).

## 4. Frontend — `frontend/src/settings/`

```ts
// settings/definitions/machine.ts
export const defaultJogVelocity = new NumberSetting(
  "Machine", "Default jog velocity", "machine.default_jog_velocity", 500, { min: 1, unit: "mm/s" });

// anywhere
import { defaultJogVelocity } from "../settings/definitions/machine";
if (defaultJogVelocity.value > 100) { ... }   // reactive
```

- **Define** every setting in `settings/definitions/*.ts`; they are
  imported eagerly by `main.ts`, so every setting exists (and is in
  the Settings view) from app start.
- **`BaseSetting`** (`core/BaseSetting.ts`): `(category, label, key,
  default, options)`; `value`, `isLoaded`, `isStored`, `load()`,
  `save(v)` → `CommandResult` (adopts the echo; failure keeps the old
  value and is reported), `reset()`. Subclasses implement `type`,
  `validate(raw)` and `component` (their editor). Subclasses declare
  **no class fields** — type config goes through `options.config` so it
  is part of the definition signature at registration time.
- **Registry** (`core/settingsRegistry.ts`): one `fetchAll()` per
  session (called by `main.ts`), cached; late registrations hydrate
  from the cache; the same key defined twice with a *different*
  definition throws, an identical one (HMR) is tolerated; `categories`
  feeds the generated Settings view (`views/SettingsView.vue`).
- **Defaults are fine**: settings only affect the UI; a value is its
  default until the stored one arrives. Another client's change shows
  up after a page reload (desync is acceptable).
- **`critical: true`**: something outside this browser depends on it.
  Never served from the cache; `value` is `null` until a fresh
  `load()` (the Settings row does that on mount).
- Types: `CheckboxSetting`, `NumberSetting`, `RangeSetting`,
  `SelectSetting`, `TextSetting`, plus custom `MacroButtonsSetting`,
  `SensorColorsSetting`, `CameraPreferencesSetting`,
  `IpCameraUrlSetting`. Editors (`settings/components/`) use the
  `useBackendSync` contract (requested value shown until the echo
  confirms it, revert + log on failure).
- Writes go through `facades/settingsFacade.ts` (generated client).

## 5. Not settings

- Safety/timing constants are **code**, not settings: the jog watchdog
  timeout (500 ms, `machine/services/jog_watchdog.py`) and the jog
  keep-alive interval (250 ms, `stores/machine.ts`).
- Per-browser display preferences (3D viewer grid / render quality)
  stay in `localStorage` on purpose — a weak tablet and a desktop may
  want different values.
