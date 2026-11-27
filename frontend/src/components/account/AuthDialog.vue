<script setup lang="ts">
// Log in or change your password (#131).
import { computed, ref, watch } from "vue";

import BaseButton from "../../ui/BaseButton.vue";
import BaseInput from "../../ui/BaseInput.vue";
import { useAuthStore } from "../../stores/authStore";
import { useConsoleStore } from "../../stores/console";

export type AuthDialogMode = "login" | "password";

const props = defineProps<{ mode: AuthDialogMode | null }>();
const emit = defineEmits<{ (e: "close"): void }>();

const auth = useAuthStore();
const consoleStore = useConsoleStore();

const username = ref("");
const password = ref("");
const repeat = ref("");
const current = ref("");
const error = ref("");
const busy = ref(false);

watch(() => props.mode, () => {
  username.value = "";
  password.value = "";
  repeat.value = "";
  current.value = "";
  error.value = "";
});

const title = computed(() => (props.mode === "password" ? "Change password" : "Log in"));

const needsRepeat = computed(() => props.mode === "password");

async function submit(): Promise<void> {
  if (busy.value || !props.mode) return;
  error.value = "";
  if (needsRepeat.value && password.value !== repeat.value) {
    error.value = "The passwords differ";
    return;
  }
  busy.value = true;
  try {
    if (props.mode === "login") await auth.login(username.value.trim(), password.value);
    else await auth.changePassword(current.value, password.value);
    consoleStore.success(props.mode === "password" ? "Password changed" : `Logged in as ${auth.name} (${auth.role})`);
    emit("close");
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div
    v-if="mode"
    class="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-4"
    data-testid="auth-dialog"
    @click.self="emit('close')"
    @keydown.esc="emit('close')"
  >
    <form
      class="w-full max-w-sm space-y-3 rounded-xl border border-gray-700 bg-gray-900 p-5"
      @submit.prevent="submit"
    >
      <h2 class="text-lg font-bold text-gray-100">{{ title }}</h2>
      <p v-if="mode === 'password' && auth.defaultPassword" class="text-xs text-amber-300">
        This account still has the default password: anyone on the network could log in as admin.
      </p>
      <label v-if="mode !== 'password'" class="block text-xs text-gray-400">
        User name
        <BaseInput v-model="username" class="mt-1 w-full" autocomplete="username" autofocus data-testid="auth-username" />
      </label>
      <label v-if="mode === 'password'" class="block text-xs text-gray-400">
        Current password
        <BaseInput v-model="current" type="password" class="mt-1 w-full" autocomplete="current-password" autofocus />
      </label>
      <label class="block text-xs text-gray-400">
        {{ mode === 'password' ? 'New password' : 'Password' }}
        <BaseInput
          v-model="password"
          type="password"
          class="mt-1 w-full"
          :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
          data-testid="auth-password"
        />
      </label>
      <label v-if="needsRepeat" class="block text-xs text-gray-400">
        Repeat the password
        <BaseInput v-model="repeat" type="password" class="mt-1 w-full" autocomplete="new-password" data-testid="auth-repeat" />
      </label>
      <p v-if="error" class="text-sm text-red-400" role="alert" data-testid="auth-error">{{ error }}</p>
      <div class="flex justify-end gap-2 pt-1">
        <BaseButton variant="secondary" type="button" @click="emit('close')">Cancel</BaseButton>
        <BaseButton variant="primary" type="submit" :loading="busy" data-testid="auth-submit">{{ title }}</BaseButton>
      </div>
    </form>
  </div>
</template>
