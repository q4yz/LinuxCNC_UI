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
} as const);
export type ModalButtonStyleValue =
  (typeof ModalButtonStyle)[keyof typeof ModalButtonStyle];

export interface ConfirmOptions {
  title?: string;
  question?: string;
  confirmButtonText?: string;
  confirmButtonStyle?: string;
  rejectButtonText?: string;
  rejectButtonStyle?: string;
  showDismissCrossButton?: boolean;
}

interface ConfirmRequest extends ConfirmOptions {
  resolve: (value: boolean) => void;
  confirmButtonStyle: string;
  rejectButtonStyle: string;
  confirmButtonText: string;
  rejectButtonText: string;
  showDismissCrossButton: boolean;
}

export const useConfirmStore = defineStore("confirm", {
  state: (): { queue: ConfirmRequest[] } => ({
    queue: [] as ConfirmRequest[],
  }),
  getters: {
    active: (state) => state.queue[0] || null,
  },
  actions: {
    enqueue(options: ConfirmOptions = {}): Promise<boolean> {
      return new Promise<boolean>((resolve) => {
        this.queue.push({
          ...options,
          resolve: resolve as (value: boolean) => void,
          confirmButtonStyle: options.confirmButtonStyle || ModalButtonStyle.PRIMARY,
          rejectButtonStyle: options.rejectButtonStyle || ModalButtonStyle.SECONDARY,
          confirmButtonText: options.confirmButtonText || "Confirm",
          rejectButtonText: options.rejectButtonText || "Cancel",
          showDismissCrossButton: options.showDismissCrossButton !== false,
        });
      });
    },
    settle(result: unknown): void {
      const request = this.queue.shift();
      request?.resolve(Boolean(result));
    },
  },
});

export function useConfirm(options: ConfirmOptions = {}): Promise<boolean> {
  return useConfirmStore().enqueue(options);
}
