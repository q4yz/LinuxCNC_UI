import { onBeforeRouteLeave } from "vue-router";

import { ModalButtonStyle, useConfirm } from "../../core/confirm.js";

// Single source of truth for the unsaved-changes prompt. The
// guard here and ``EditorView.vue`` both render the same dialog;
// both import these constants so a copy change shows up in both
// places at once (no more "German here / English there" mismatch).
export const UNSAVED_PROMPT = {
  title: "Unsaved changes",
  question: "Are you sure you want to close? Any unsaved changes will be lost.",
  confirmText: "Close",
  rejectText: "Cancel",
};

export function useUnsavedChangesGuard(hasUnsavedChanges) {
  return onBeforeRouteLeave(async () => {
    if (!hasUnsavedChanges()) return true;
    return useConfirm({
      title: UNSAVED_PROMPT.title,
      question: UNSAVED_PROMPT.question,
      confirmButtonText: UNSAVED_PROMPT.confirmText,
      confirmButtonStyle: ModalButtonStyle.DANGER,
      rejectButtonText: UNSAVED_PROMPT.rejectText,
      rejectButtonStyle: ModalButtonStyle.SECONDARY,
      showDismissCrossButton: false,
    });
  });
}
