// Who is using this client (#131): the logged-in account, or a viewer.
//
// ``refresh()`` asks the backend (``/auth/me``): the role and what it may
// do (``can``). A stored token the backend no longer accepts (password
// changed elsewhere, account deleted) is dropped — the client is a
// viewer again. Like SSH there is always a login: the default admin
// ``remora`` / ``remora``; ``defaultPassword`` asks to change it.
import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { authFacade, type CurrentUserResponse, type LoginResponse } from "../facades/authFacade";
import { getToken, setToken } from "../core/authToken";

export const useAuthStore = defineStore("auth", () => {
  const me = ref<CurrentUserResponse | null>(null);
  const loaded = ref(false);

  const role = computed(() => me.value?.role ?? "viewer");
  const name = computed(() => me.value?.name ?? "");
  const authenticated = computed(() => me.value?.authenticated === true);
  /** Logged in with the default account's default password. */
  const defaultPassword = computed(() => me.value?.default_password === true);
  /** Watching without a login. */
  const isGuest = computed(() => loaded.value && !authenticated.value);

  /** The role may do it without asking (``core/permissions.py``). Before the
   * first answer nothing is withheld — the backend decides anyway. */
  function can(permission: string): boolean {
    if (!me.value) return true;
    return me.value.permissions?.[permission] === "allow";
  }

  async function refresh(): Promise<void> {
    try {
      const current = await authFacade.me();
      if (getToken() && !current.authenticated) {
        // the backend no longer takes this token
        setToken(null);
      }
      me.value = current;
    } catch {
      // system backend unreachable: keep what we knew
    } finally {
      loaded.value = true;
    }
  }

  function apply(response: LoginResponse): void {
    setToken(response.token);
    me.value = response.user;
    loaded.value = true;
  }

  async function login(username: string, password: string): Promise<void> {
    apply(await authFacade.login(username, password));
  }

  async function changePassword(current: string, next: string): Promise<void> {
    apply(await authFacade.changePassword(current, next));
  }

  async function logout(): Promise<void> {
    setToken(null);
    await refresh();
  }

  async function logoutEverywhere(): Promise<void> {
    await authFacade.logoutEverywhere();
    await logout();
  }

  return {
    me, loaded, role, name, authenticated, defaultPassword, isGuest,
    can, refresh, login, changePassword, logout, logoutEverywhere,
  };
});
