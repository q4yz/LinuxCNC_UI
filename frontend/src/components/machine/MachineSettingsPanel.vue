<script setup lang="ts">
// Machine module settings panel.
//
// Surfaces every persisted knob the backend's ``MachineSettings``
// Pydantic model declares (the schema lives at
// ``backend/models/axis_settings.py``) plus the new
// ``macroButtons`` editor for the per-axis DRO rows.
//
// Backend note: ``jog_watchdog_timeout_ms`` and
// ``keepalive_interval_ms`` only take effect on the next backend
// boot; the UI does not promise live updates for those.
//
// Persistence: every field writes through
// ``createModuleSettings('axis').writeKey(name, value)``. The
// editor debounces each field's ``change`` event so we do not
// flood the server while the operator types.
//
// Naming note: the machine module has a historical id mismatch
// between the frontend and the backend. The frontend store
// (``stores/machine.ts``) declares its Pinia id as
// ``"machine"`` (the canonical domain id), but the backend's
// ``_MODULE_DOMAINS[0]`` mounts this module's settings router
// under ``id: "axis"`` — the URL is therefore
// ``/api/v1/modules/axis/settings/...``. Both this panel and
// ``DroPanel.vue`` therefore pass ``"axis"`` to the settings
// client so the read/write surfaces stay on the same
// ``<data_root>/modules/axis/settings.json`` file. The settings
// URL is the only place where ``"axis"`` shows up. A future
// rename that aligns the two sides should pick one name and
// update every reference in lockstep.

import { onMounted, ref } from "vue";

import { createModuleSettings } from "../../core/settings/createModuleSettings";
import { useMacroButtonConfig, MacroButtonEditor } from "../../ui";

const settings = createModuleSettings("axis");

const loading = ref(false);
const saving = ref(false);
const errorMessage = ref("");
const statusMessage = ref("");

// Field-level state. Each entry holds the local draft so per-field
// writes do not stomp sibling fields. Booleans / numbers / strings
// share the same writeKey path — the backend stores the value as
// the Pydantic-declared type.
const fields = ref({
  jog_watchdog_timeout_ms: 500,
  default_jog_velocity: 500,
  keepalive_interval_ms: 250,
  estop_disables_power: true,
});

// Macro buttons (one row per axis DRO slot). The settings
// moduleId is ``"axis"`` (not ``manifest.id`` of ``"machine"``)
// to match the backend's ``_MODULE_DOMAINS[0]`` mount — see the
// header comment for the full rationale.
const buttonConfig = useMacroButtonConfig("axis");

const SLOTS = [
  { id: "dro.x", label: "X axis row" },
  { id: "dro.y", label: "Y axis row" },
  { id: "dro.z", label: "Z axis row" },
];

onMounted(async () => {
  loading.value = true;
  try {
    const payload = await settings.readAll();
    fields.value = {
      jog_watchdog_timeout_ms:
        typeof payload.jog_watchdog_timeout_ms === "number"
          ? payload.jog_watchdog_timeout_ms
          : fields.value.jog_watchdog_timeout_ms,
      default_jog_velocity:
        typeof payload.default_jog_velocity === "number"
          ? payload.default_jog_velocity
          : fields.value.default_jog_velocity,
      keepalive_interval_ms:
        typeof payload.keepalive_interval_ms === "number"
          ? payload.keepalive_interval_ms
          : fields.value.keepalive_interval_ms,
      estop_disables_power:
        typeof payload.estop_disables_power === "boolean"
          ? payload.estop_disables_power
          : fields.value.estop_disables_power,
    };
    await buttonConfig.refresh();
  } catch (requestError) {
    errorMessage.value =
      requestError instanceof Error
        ? requestError.message
        : "Failed to load machine settings";
  } finally {
    loading.value = false;
  }
});

// The MacroButtonEditor emits ``update:modelValue`` on every
// committed change (one per ``change`` event on each input).
// ``useMacroButtonConfig.persist`` is the single source of truth
// for write-through — there is no ``watch(() => buttons.value)``
// here because that would re-fire on every nested change and
// re-emit through ``persist`` → ``writeKey``, producing the
// request spam observed when this component first shipped.
// ``persist`` itself no longer mutates ``buttons.value`` (see
// ``useMacroButtonConfig.ts``) so the only path that triggers a
// write is the editor's emit.

async function commitField(name, raw) {
  statusMessage.value = "";
  saving.value = true;
  try {
    const payload = await settings.writeKey(name, raw);
    if (payload && payload[name] !== undefined) {
      fields.value[name] = payload[name];
    }
    statusMessage.value = `Saved ${name}.`;
  } catch (requestError) {
    errorMessage.value =
      requestError instanceof Error
        ? requestError.message
        : `Failed to save ${name}`;
  } finally {
    saving.value = false;
  }
}

function onCommitJogWatchdog(event) {
  const value = Number(event.target.value);
  if (!Number.isFinite(value)) return;
  commitField("jog_watchdog_timeout_ms", value);
}

function onCommitJogVelocity(event) {
  const value = Number(event.target.value);
  if (!Number.isFinite(value)) return;
  commitField("default_jog_velocity", value);
}

function onCommitKeepalive(event) {
  const value = Number(event.target.value);
  if (!Number.isFinite(value)) return;
  commitField("keepalive_interval_ms", value);
}

function onCommitEstopDisablesPower(event) {
  commitField("estop_disables_power", event.target.checked);
}
</script>

<template>
  <div class="space-y-8">
    <p
      v-if="loading"
      class="text-xs text-gray-500"
      role="status"
    >
      Loading machine settings…
    </p>
    <p
      v-else-if="errorMessage"
      class="text-xs text-red-300"
      role="alert"
    >
      {{ errorMessage }}
    </p>
    <p
      v-else-if="statusMessage"
      class="text-xs text-green-300"
      role="status"
    >
      {{ statusMessage }}
    </p>

    <section class="space-y-3">
      <header>
        <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Jog safety
        </h3>
        <p class="mt-1 text-xs text-gray-400">
          Continuous-jog watchdog window and the frontend's
          keep-alive cadence. Changes take effect on the next backend
          boot.
        </p>
      </header>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label class="text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">
            Jog watchdog timeout (ms)
          </span>
          <input
            type="number"
            min="100"
            max="5000"
            step="50"
            :value="fields.jog_watchdog_timeout_ms"
            :disabled="saving"
            class="w-full rounded border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-100 focus:border-blue-500 focus:outline-none disabled:opacity-60"
            data-test="machine-jog-watchdog"
            @change="onCommitJogWatchdog"
          >
        </label>
        <label class="text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">
            Keep-alive interval (ms)
          </span>
          <input
            type="number"
            min="50"
            max="2000"
            step="25"
            :value="fields.keepalive_interval_ms"
            :disabled="saving"
            class="w-full rounded border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-100 focus:border-blue-500 focus:outline-none disabled:opacity-60"
            data-test="machine-keepalive"
            @change="onCommitKeepalive"
          >
        </label>
      </div>
    </section>

    <section class="space-y-3">
      <header>
        <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Default jog velocity
        </h3>
        <p class="mt-1 text-xs text-gray-400">
          Velocity (mm/min) used by a fresh continuous jog when the
          operator has not chosen another value.
        </p>
      </header>

      <label class="text-sm text-gray-200">
        <span class="mb-1 block text-xs font-medium text-gray-400">
          Default jog velocity (mm/min)
        </span>
        <input
          type="number"
          min="1"
          step="10"
          :value="fields.default_jog_velocity"
          :disabled="saving"
          class="w-full rounded border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-100 focus:border-blue-500 focus:outline-none disabled:opacity-60"
          data-test="machine-jog-velocity"
          @change="onCommitJogVelocity"
        >
      </label>
    </section>

    <section class="space-y-3">
      <header>
        <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">
          E-STOP / power policy
        </h3>
        <p class="mt-1 text-xs text-gray-400">
          Native hardware transitions remain authoritative; this
          flag is reserved for higher-level power workflows.
        </p>
      </header>

      <label class="flex cursor-pointer select-none items-center gap-2 text-sm text-gray-200">
        <input
          type="checkbox"
          :checked="fields.estop_disables_power"
          :disabled="saving"
          class="h-5 w-5 rounded border-gray-600 bg-gray-900 text-blue-500 focus:ring-blue-500"
          data-test="machine-estop-power"
          @change="onCommitEstopDisablesPower"
        >
        E-Stop disables machine power
      </label>
    </section>

    <section class="space-y-3">
      <header>
        <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Custom buttons
        </h3>
      </header>
      <MacroButtonEditor
        :model-value="buttonConfig.buttons.value"
        :slots="SLOTS"
        module-id="machine"
        description="Add a custom button next to each axis row in the DRO. The button runs a macro when clicked; leave the macro empty to hide the button."
        @update:model-value="(next) => buttonConfig.persist(next)"
      />
    </section>
  </div>
</template>