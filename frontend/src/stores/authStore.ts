// Who is using this client (#131): the logged-in account, or a viewer.
//
// ``refresh()`` asks the backend (``/auth/me``): the role and what it may
// do (``can``). A stored token the backend no longer accepts (password
// changed elsewhere, account deleted) is dropped — the client is a
// viewer again. Until the first account exists every caller is the
// local admin and ``needsSetup`` offers to create it.
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
  const accountsExist = computed(() => me.value?.accounts_exist === true);
  const needsSetup = computed(() => loaded.value && !accountsExist.value);
  /** Watching without a login (accounts exist, none logged in). */
  const isGuest = computed(() => loaded.value && accountsExist.value && !authenticated.value);

  /** The role may do it without asking (``core/permissions.py``). Before the
   * first answer nothing is withheld — the backend decides anyway. */
  function can(permission: string): boolean {
    if (!me.value) return true;
    return me.value.permissions?.[permission] === "allow";
  }

  async function refresh(): Promise<void> {
    try {
      const current = await authFacade.me();
      if (getToken() && current.accounts_exist && !current.authenticated) {
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

  async function setup(username: string, password: string): Promise<void> {
    apply(await authFacade.setup(username, password));
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
    me, loaded, role, name, authenticated, accountsExist, needsSetup, isGuest,
    can, refresh, login, setup, changePassword, logout, logoutEverywhere,
  };
});
