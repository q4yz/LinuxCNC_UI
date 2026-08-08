import { onBeforeRouteLeave } from "vue-router";

import { ModalButtonStyle, useConfirm } from "../../core/confirm.js";

export function useUnsavedChangesGuard(hasUnsavedChanges) {
  return onBeforeRouteLeave(async () => {
    if (!hasUnsavedChanges()) return true;
    return useConfirm({
      title: "Ungespeicherte Änderungen",
      question: "Möchten Sie diese Seite wirklich verlassen?",
      description: "Alle nicht gespeicherten Eingaben gehen verloren und können nicht wiederhergestellt werden.",
      confirmButtonText: "Seite verlassen",
      confirmButtonStyle: ModalButtonStyle.DANGER,
      rejectButtonText: "Hier bleiben",
      rejectButtonStyle: ModalButtonStyle.SECONDARY,
      showDismissCrossButton: false,
    });
  });
}
