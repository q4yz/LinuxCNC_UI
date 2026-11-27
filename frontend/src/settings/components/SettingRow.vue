<script setup lang="ts">
// One row of the generated Settings view: label, help text, the
// setting's own editor (``setting.component``) and a reset-to-default
// button. Critical settings are read fresh every time the row mounts —
// they are never trusted from the session cache.
//
// Who changes what: the admin's values are the shared set (viewers and
// the agent see only those); a user's changes are their own, and their
// "reset" brings back the admin's value. Machine-wide settings (read by
// the backends) only an admin changes.
import { computed, onMounted } from "vue";
import type { BaseSetting } from "../core/BaseSetting";
import { useAuthStore } from "../../stores/authStore";

const props = defineProps<{ setting: BaseSetting<unknown> }>();
const auth = useAuthStore();

const isAdmin = computed(() => auth.can("config.write"));
const canWrite = computed(() => auth.can("settings.write"));
/** This login may change the setting. */
const editable = computed(() => canWrite.value && (isAdmin.value || !props.setting.isMachine));
/** A user's own value (a reset brings back the admin's). */
const personal = computed(() => !isAdmin.value && props.setting.isPersonal);
const showReset = computed(() => editable.value && (isAdmin.value ? props.setting.isStored : personal.value));
const readOnlyNote = computed(() => {
  if (editable.value) return "";
  return canWrite.value ? "Set by the admin for everyone" : "Log in to change it";
});

onMounted(() => {
  if (props.setting.critical) void props.setting.load();
});
</script>

<template>
  <div
      class="flex gap-4 rounded bg-gray-900/60 border border-gray-700 px-4 py-3"
      :class="setting.wide ? 'flex-col' : 'flex-wrap items-center justify-between'"
  >
    <div class="min-w-0 flex-1">
      <div class="text-sm font-medium text-gray-200">
        {{ setting.label }}
        <span
            v-if="setting.critical"
            class="ml-2 rounded border border-amber-700 px-1 text-[10px] uppercase tracking-wider text-amber-300"
            title="Read fresh from the backend every time — other parts of the system depend on it"
        >live</span>
        <span
            v-if="personal"
            class="ml-2 rounded border border-sky-700 px-1 text-[10px] uppercase tracking-wider text-sky-300"
            title="Your own value — the others still see the admin's"
            :data-testid="`setting-personal-${setting.key}`"
        >yours</span>
        <span
            v-else-if="isAdmin && setting.isStored"
            class="ml-2 rounded border border-gray-600 px-1 text-[10px] uppercase tracking-wider text-gray-400"
            title="Your values are the shared set: viewers and the agent see them, users start from them"
        >shared</span>
      </div>
      <p v-if="setting.description" class="mt-0.5 text-xs text-gray-400">{{ setting.description }}</p>
      <p class="mt-0.5 font-mono text-[10px] text-gray-500">{{ setting.key }}</p>
      <p
          v-if="readOnlyNote"
          class="mt-0.5 text-[11px] text-amber-300/80"
          :data-testid="`setting-readonly-${setting.key}`"
      >{{ readOnlyNote }}</p>
    </div>
    <div class="flex gap-2" :class="setting.wide ? 'w-full flex-col items-stretch' : 'items-center'">
      <fieldset :disabled="!editable" class="contents" :class="editable ? '' : 'opacity-60'">
        <component :is="setting.component" :setting="setting" />
      </fieldset>
      <button
          v-if="showReset"
          type="button"
          class="text-xs text-gray-400 hover:text-gray-200 underline"
          :class="setting.wide ? 'self-start' : ''"
          :title="personal ? 'Drop your own value — the admin\'s applies again' : `Reset to default (${JSON.stringify(setting.defaultValue)})`"
          :data-testid="`setting-reset-${setting.key}`"
          @click="setting.reset()"
      >
        {{ personal ? "use the admin's" : "reset" }}
      </button>
    </div>
  </div>
</template>
