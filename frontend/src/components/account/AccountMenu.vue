<script setup lang="ts">
// The account control at the bottom of the sidebar (#131):
//   * no account yet  -> "Create admin" (everyone is admin until then)
//   * not logged in   -> "Log in" (watching only: the viewer role)
//   * logged in       -> name + role; change password, the slicer API key,
//                        log out, log out on every device.
import { computed, onMounted, ref } from "vue";

import { getToken } from "../../core/authToken";
import { useAuthStore } from "../../stores/authStore";
import { useConsoleStore } from "../../stores/console";
import AuthDialog, { type AuthDialogMode } from "./AuthDialog.vue";

defineProps<{ collapsed: boolean }>();

const auth = useAuthStore();
const consoleStore = useConsoleStore();
const dialog = ref<AuthDialogMode | null>(null);
const menuOpen = ref(false);

onMounted(() => {
  void auth.refresh();
});

const label = computed(() => {
  if (auth.needsSetup) return "Create admin";
  if (!auth.authenticated) return "Log in";
  return auth.name;
});

const sublabel = computed(() => {
  if (auth.needsSetup) return "no accounts yet";
  if (!auth.authenticated) return "viewer: watching only";
  return auth.role;
});

function onClick(): void {
  if (auth.needsSetup) dialog.value = "setup";
  else if (!auth.authenticated) dialog.value = "login";
  else menuOpen.value = !menuOpen.value;
}

async function copyApiKey(): Promise<void> {
  menuOpen.value = false;
  const token = getToken();
  if (!token) return;
  try {
    await navigator.clipboard.writeText(token);
    consoleStore.success("API key copied: paste it as the slicer's OctoPrint API key");
  } catch {
    window.prompt("API key for the slicer (OctoPrint API key):", token);
  }
}

async function logout(everywhere: boolean): Promise<void> {
  menuOpen.value = false;
  try {
    if (everywhere) await auth.logoutEverywhere();
    else await auth.logout();
    consoleStore.info(everywhere ? "Logged out on every device" : "Logged out");
  } catch (err) {
    consoleStore.error(`Log out failed: ${err instanceof Error ? err.message : String(err)}`);
  }
}

function openPassword(): void {
  menuOpen.value = false;
  dialog.value = "password";
}
</script>

<template>
  <div class="relative border-t border-gray-700" data-testid="account-menu">
    <button
      type="button"
      class="flex w-full items-center px-4 py-3 text-left outline-none transition-colors hover:bg-gray-700"
      :class="[
        collapsed ? 'justify-center' : 'justify-start',
        auth.needsSetup ? 'text-amber-300' : auth.authenticated ? 'text-gray-200' : 'text-gray-400',
      ]"
      :title="collapsed ? `${label} (${sublabel})` : ''"
      data-testid="account-button"
      @click="onClick"
    >
      <!-- person icon -->
      <svg class="h-6 w-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
      </svg>
      <span v-if="!collapsed" class="ml-3 min-w-0">
        <span class="block truncate font-medium">{{ label }}</span>
        <span class="block truncate text-[11px] uppercase tracking-wider text-gray-500">{{ sublabel }}</span>
      </span>
    </button>

    <div
      v-if="menuOpen"
      class="absolute bottom-full left-2 z-50 mb-1 w-56 rounded-lg border border-gray-700 bg-gray-900 py-1 text-sm"
      data-testid="account-actions"
    >
      <button type="button" class="block w-full px-4 py-2 text-left hover:bg-gray-800" @click="openPassword">
        Change password
      </button>
      <button type="button" class="block w-full px-4 py-2 text-left hover:bg-gray-800" @click="copyApiKey">
        Copy API key (slicer upload)
      </button>
      <button type="button" class="block w-full px-4 py-2 text-left hover:bg-gray-800" data-testid="account-logout"
              @click="logout(false)">
        Log out
      </button>
      <button type="button" class="block w-full px-4 py-2 text-left text-red-300 hover:bg-gray-800" @click="logout(true)">
        Log out on every device
      </button>
    </div>

    <AuthDialog :mode="dialog" @close="dialog = null" />
  </div>
</template>
