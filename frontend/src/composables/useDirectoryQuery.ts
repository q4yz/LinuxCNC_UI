// Keeps a file explorer's open directory in the URL.
//
// The explorers are re-created from scratch whenever the operator
// leaves the page (opening a file in an editor unmounts them), so a
// plain `ref` would drop them back at the root on return. Holding the
// directory in the query string instead makes the URL the single
// source of truth: going back — via the editor's Close button, the
// browser's back button, or a bookmarked link — lands on the same
// folder, and forward/back step through it like any other navigation.
//
// The returned ref is writable, so call sites keep assigning to it
// (`currentDirectory.value = entry.path`) exactly as they did when it
// was local state.

import { computed, type WritableComputedRef } from "vue";
import { useRoute, useRouter } from "vue-router";

export function useDirectoryQuery(key: string): WritableComputedRef<string> {
  const route = useRoute();
  const router = useRouter();

  return computed<string>({
    get() {
      const raw = route.query[key];
      return typeof raw === "string" ? raw : "";
    },
    set(next) {
      const query = { ...route.query };
      // The root folder is the default — leave it out so a plain
      // `/config` URL stays clean.
      if (next) query[key] = next;
      else delete query[key];
      // `replace`: browsing folders refines where you are rather than
      // stacking a history entry per click, so Close/back still returns
      // to the page you came from — with this folder restored.
      void router.replace({ query });
    },
  });
}
