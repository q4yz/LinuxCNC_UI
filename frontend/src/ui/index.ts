// Shared UI primitive barrel.
//
// Every component in ``frontend/src/ui/`` is a single-purpose,
// dependency-light Vue component intended to replace the ad-hoc
// class soup sprinkled across the rest of the codebase. Consumers
// import from this barrel rather than from the individual files so
// the import surface stays narrow:
//
//     import { Button, Icon, Drawer, Confirm } from "@/ui";
//
// (In practice consumers use the relative path; this barrel is for
// grep-ability — a future ESM alias in ``vite.config.js`` can move
// the import to a true ``@/ui`` once the project's alias surface
// is ready.)
//
// Add new primitives here as the codebase grows. Keep the list
// small — primitives are for things that appear in 3+ unrelated
// call sites; one-off UI stays in the consuming component.

export { default as Button } from "./Button.vue";
export { default as Icon } from "./Icon.vue";
export { default as Drawer } from "./Drawer.vue";
export { default as Confirm } from "./Confirm.vue";
