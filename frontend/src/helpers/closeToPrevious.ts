// How a full-screen editor gets out of the way when it's closed.
//
// Pushing a fixed route (`{ name: 'config' }`) throws away where the
// operator actually was: the explorers keep their open folder in the
// URL, so a fresh push lands them back at the root. Stepping back in
// history restores that URL — and returns to whichever page opened
// the editor, not just the one page we happened to hard-code.
//
// A directly-opened editor (deep link, bookmark, fresh tab) has no
// in-app entry behind it; Vue Router leaves `history.state.back` null
// in that case, and we push the fallback route instead so Close never
// dead-ends on a blank page or walks out of the app.

import type { Router } from "vue-router";

export function closeToPrevious(router: Router, fallbackName: string): void {
  const previous = (window.history.state as { back?: string | null } | null)?.back;
  if (previous) {
    router.back();
    return;
  }
  router
    .push({ name: fallbackName })
    .catch((err) => console.error("Router error on close:", err));
}
