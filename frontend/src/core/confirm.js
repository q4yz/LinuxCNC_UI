import { defineStore } from "pinia";

export const ModalButtonStyle = Object.freeze({
  SUCCESS: "success",
  INFO: "info",
  DANGER: "danger",
  WARNING: "warning",
  PRIMARY: "primary",
  PRIMARY_OUTLINE: "primary-outline",
  SECONDARY: "secondary",
  SECONDARY_OUTLINE: "secondary-outline",
});

export const useConfirmStore = defineStore("confirm", {
  state: () => ({
    queue: [],
  }),
  getters: {
    active: (state) => state.queue[0] || null,
  },
  actions: {
    enqueue(options) {
      return new Promise((resolve) => {
        this.queue.push({
          ...options,
          resolve,
          confirmButtonStyle: options.confirmButtonStyle || ModalButtonStyle.PRIMARY,
          rejectButtonStyle: options.rejectButtonStyle || ModalButtonStyle.SECONDARY,
          confirmButtonText: options.confirmButtonText || "Confirm",
          rejectButtonText: options.rejectButtonText || "Cancel",
          showDismissCrossButton: options.showDismissCrossButton !== false,
        });
      });
    },
    settle(result) {
      const request = this.queue.shift();
      request?.resolve(Boolean(result));
    },
  },
});

export function useConfirm(options = {}) {
  return useConfirmStore().enqueue(options);
}
