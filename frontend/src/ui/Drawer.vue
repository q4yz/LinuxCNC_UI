<script setup>
// Shared slide-out drawer primitive.
//
// Use cases today include the sidebar collapse (currently inline
// in ``AppSidebar.vue:46-89`` with its own ``isCollapsed`` ref) and
// any future slide-over panels — alarms, history, settings detail.
// The component owns the open/close lifecycle (backdrop click,
// ``Escape`` key, transition), so consumers just declare ``v-model:open``
// or wire ``open`` and ``@close``.
//
// Position: ``right`` (the canonical operator-side anchor; matches
// the global ``ToastContainer.vue`` after we re-anchored that to the
// bottom-right). ``left`` is provided for symmetry — the sidebar
// collapse could swap to ``Drawer`` on ``position="left"`` in a
// later PR. Top / bottom are reserved for a future top-banner
// notification surface; the ``side`` API is the single source of
// truth.
//
// CSS transitions: the panel slides in/out via a translate-based
// transform. Vue's ``<Transition>`` handles the timing so the
// ``open`` prop reflects the post-animation state. ``body`` lock
// would be a real concern on mobile; for the operator console the
// drawer is a narrow overlay so we leave the body alone.

import { computed, onBeforeUnmount, onMounted, watch } from "vue";

const props = defineProps({
  // Two-way bound — ``v-model:open``. The drawer is open when this
  // is true. Setting it to false from outside triggers the close
  // transition and emits ``update:open``.
  open: { type: Boolean, default: false },
  // Side of the viewport the drawer slides in from.
  side: {
    type: String,
    default: "right",
    validator: (s) => ["right", "left"].includes(s),
  },
  // Tailwind max-width class so consumers control the panel
  // footprint. Defaults to ``w-96`` (24 rem) — wider than the
  // existing inline sidebar collapse so a generic panel can host
  // alarm / history lists.
  width: { type: String, default: "w-96" },
  // Whether clicking the backdrop closes the drawer. Default true
  // (matches every modal pattern in the dashboard). Operators
  // needing a "must explicitly close" drawer can pass false.
  closeOnBackdrop: { type: Boolean, default: true },
  // Whether the ``Escape`` key closes the drawer. Same default as
  // the backdrop behaviour. Listeners attach on mount and detach
  // on unmount so the keypress only fires when the drawer is on
  // screen — multiple drawers in the same page don't stack their
  // handlers.
  closeOnEsc: { type: Boolean, default: true },
});

const emit = defineEmits(["update:open", "close"]);

// Transition classes. The drawer slides in from its anchor side
// when ``v-if`` enters; the same animation runs in reverse on
// exit. Vue's ``<Transition>`` keeps the panel mounted for the
// duration of the leave transition so the animation isn't cut off.
const enterClasses = computed(() =>
  props.side === "left" ? "translate-x-0" : "translate-x-0",
);
const leaveClasses = computed(() =>
  props.side === "left" ? "-translate-x-full" : "translate-x-full",
);

const panelPositionClasses = computed(() => {
  // Anchor the panel to the requested viewport edge.
  return props.side === "left" ? "left-0" : "right-0";
});

const initialTranslateClasses = computed(() =>
  props.side === "left" ? "-translate-x-full" : "translate-x-full",
);

function onBackdropClick() {
  if (!props.closeOnBackdrop) return;
  emitClose();
}

function onKeydown(event) {
  if (!props.closeOnEsc) return;
  if (event.key === "Escape" && props.open) {
    emitClose();
  }
}

function emitClose() {
  emit("update:open", false);
  emit("close");
}

// Attach the keyboard listener once on mount. ``watch`` is not
// needed here — the listener itself checks the ``open`` prop before
// reacting, so we do not need to detach it on close.
onMounted(() => {
  if (typeof window !== "undefined") {
    window.addEventListener("keydown", onKeydown);
  }
});
onBeforeUnmount(() => {
  if (typeof window !== "undefined") {
    window.removeEventListener("keydown", onKeydown);
  }
});

// Convenience: when ``open`` flips false from outside (parent
// state-driven), the VueTransition already runs the leave hook
// automatically. We just emit ``update:open`` only on user
// interaction (backdrop / Escape / explicit ``@close``). No
// re-emitting on prop changes.
watch(
  () => props.open,
  () => {
    /* no-op — the parent owns the open-state mutation */
  },
);
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-150"
      leave-active-class="transition-opacity duration-150"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-40 bg-black/60"
        data-test="drawer-backdrop"
        @click="onBackdropClick"
      ></div>
    </Transition>

    <Transition
      :enter-active-class="'transition-transform duration-200 ease-out ' + enterClasses"
      :leave-active-class="'transition-transform duration-200 ease-in ' + leaveClasses"
      :enter-from-class="initialTranslateClasses"
      :leave-to-class="leaveClasses"
    >
      <aside
        v-if="open"
        :class="[
          'fixed top-0 bottom-0 z-50 bg-gray-800 border-gray-700 shadow-2xl',
          'flex flex-col overflow-hidden',
          panelPositionClasses,
          width,
        ]"
        data-test="drawer-panel"
        :data-side="side"
        role="dialog"
        aria-modal="true"
      >
        <!-- Header slot for title / close button. Most drawers
             render their own ``<header>`` here so the consumer
             controls the chrome. -->
        <slot name="header" />
        <!-- Body content. Scrolls independently so a long list
             inside the drawer does not push the header off the
             viewport. -->
        <div class="flex-1 overflow-y-auto">
          <slot />
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>
