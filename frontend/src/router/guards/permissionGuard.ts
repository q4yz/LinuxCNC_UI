// Tabs only some roles may open (#131): a route's ``meta.permission``
// (``core/permissions.py``; Config and Debug are admin-only). The sidebar
// hides such a tab; this guard turns a typed URL (``#/config``) back to
// the Dashboard, and so does a logout while on one.
import type { RouteLocationNormalized, Router } from "vue-router";

import { useAuthStore } from "../../stores/authStore";

/** The permission a route needs, or ``undefined``. */
export function routePermission(route: Pick<RouteLocationNormalized, "meta">): string | undefined {
  const value = route.meta?.permission;
  return typeof value === "string" ? value : undefined;
}

/** May the current login open a tab that needs ``permission``? Unknown
 * yet (no answer from the backend): no — the tab appears once it knows. */
export function mayOpen(permission: string | undefined): boolean {
  if (!permission) return true;
  const auth = useAuthStore();
  return auth.me !== null && auth.can(permission);
}

export function installPermissionGuard(router: Router): void {
  router.beforeEach(async (to) => {
    const permission = routePermission(to);
    if (!permission) return true;
    const auth = useAuthStore();
    if (auth.me === null) await auth.refresh();
    return mayOpen(permission) ? true : { name: "dashboard" };
  });
}
