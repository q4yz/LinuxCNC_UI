<script setup lang="ts">
// Accounts (#131, admins): add, change role, set a new password, delete.
// The backend keeps the last admin.
import { onMounted, ref } from "vue";

import BaseButton from "../../ui/BaseButton.vue";
import BaseInput from "../../ui/BaseInput.vue";
import { authFacade, type UserResponse } from "../../facades/authFacade";
import { useAuthStore } from "../../stores/authStore";
import { useConsoleStore } from "../../stores/console";

const auth = useAuthStore();
const consoleStore = useConsoleStore();

const users = ref<UserResponse[]>([]);
const roles = ref<string[]>(["admin", "user", "viewer"]);
const error = ref("");
const newName = ref("");
const newPassword = ref("");
const newRole = ref("user");
const busy = ref(false);

const ROLE_HELP: Record<string, string> = {
  admin: "everything: configuration, updates, users",
  user: "runs the machine: jog, programs, heaters, calibration",
  viewer: "watches (like anyone not logged in)",
};

async function load(): Promise<void> {
  try {
    const list = await authFacade.listUsers();
    users.value = list.users;
    roles.value = list.roles;
    error.value = "";
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

onMounted(load);

async function run(what: string, action: () => Promise<unknown>): Promise<void> {
  busy.value = true;
  try {
    await action();
    consoleStore.success(what);
    await load();
    await auth.refresh();
  } catch (err) {
    consoleStore.error(`${what} failed: ${err instanceof Error ? err.message : String(err)}`, { popup: true });
  } finally {
    busy.value = false;
  }
}

function add(): void {
  const name = newName.value.trim();
  void run(`User '${name}' added`, async () => {
    await authFacade.createUser(name, newPassword.value, newRole.value);
    newName.value = "";
    newPassword.value = "";
  });
}

function setRole(user: UserResponse, role: string): void {
  void run(`'${user.name}' is ${role} now`, () => authFacade.updateUser(user.name, { role }));
}

function resetPassword(user: UserResponse): void {
  const password = window.prompt(`New password for '${user.name}' (their sessions end):`);
  if (!password) return;
  void run(`Password of '${user.name}' changed`, () => authFacade.updateUser(user.name, { password }));
}

function remove(user: UserResponse): void {
  if (!window.confirm(`Delete the account '${user.name}'?`)) return;
  void run(`User '${user.name}' deleted`, () => authFacade.deleteUser(user.name));
}
</script>

<template>
  <div class="space-y-4" data-testid="users-panel">
    <p class="text-xs text-gray-400">
      Anyone who is not logged in can watch (viewer). A login lasts on its device until it logs out,
      its password changes or the account is deleted.
    </p>
    <p v-if="error" class="text-sm text-red-400" role="alert">{{ error }}</p>

    <table class="w-full text-sm text-gray-200">
      <thead class="text-left text-xs uppercase tracking-wider text-gray-400">
        <tr><th class="py-2">User</th><th class="py-2">Role</th><th class="py-2 text-right">Actions</th></tr>
      </thead>
      <tbody>
        <tr v-for="user in users" :key="user.name" class="border-t border-gray-700" :data-testid="`user-row-${user.name}`">
          <td class="py-2 font-medium">
            {{ user.name }}
            <span v-if="user.name === auth.name" class="ml-1 text-xs text-gray-500">(you)</span>
          </td>
          <td class="py-2">
            <select
              :value="user.role"
              :disabled="busy"
              class="rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs"
              :title="ROLE_HELP[user.role] ?? ''"
              @change="setRole(user, ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="role in roles" :key="role" :value="role">{{ role }}</option>
            </select>
          </td>
          <td class="py-2 text-right">
            <div class="flex flex-wrap justify-end gap-2">
              <BaseButton size="sm" variant="secondary" :disabled="busy" @click="resetPassword(user)">New password</BaseButton>
              <BaseButton size="sm" variant="danger" :disabled="busy" @click="remove(user)">Delete</BaseButton>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <form class="flex flex-wrap items-end gap-2 border-t border-gray-700 pt-4" @submit.prevent="add">
      <label class="text-xs text-gray-400">
        User name
        <BaseInput v-model="newName" class="mt-1 block w-40" autocomplete="off" data-testid="users-new-name" />
      </label>
      <label class="text-xs text-gray-400">
        Password
        <BaseInput v-model="newPassword" type="password" class="mt-1 block w-40" autocomplete="new-password" />
      </label>
      <label class="text-xs text-gray-400">
        Role
        <select v-model="newRole" class="mt-1 block rounded border border-gray-600 bg-gray-900 px-2 py-2 text-sm">
          <option v-for="role in roles" :key="role" :value="role">{{ role }}</option>
        </select>
      </label>
      <BaseButton type="submit" variant="primary" :disabled="busy || !newName.trim() || !newPassword">Add user</BaseButton>
    </form>
    <ul class="text-xs text-gray-500">
      <li v-for="role in roles" :key="role"><b>{{ role }}</b>: {{ ROLE_HELP[role] }}</li>
    </ul>
  </div>
</template>
