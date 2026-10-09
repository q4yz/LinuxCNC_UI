// System update tracking. The update script (`scripts/update.sh`)
// restarts the very services the UI talks to, so the UI cannot infer
// "finished" from the services being reachable — temporary outages and
// restarts look the same. Instead it follows the status the script
// writes (`GET /api/v1/system/update/status`):
//
//   * the overlay stays while the status is `running` for our run id,
//     and while the system service cannot be reached at all;
//   * `done` (written only after the restarted services answered)
//     reloads the page so the freshly built frontend is loaded; the
//     success notification is shown after that reload;
//   * `failed` keeps the overlay open with the reason + log tail and
//     shows an error notification.
//
// `resume()` runs at app start and then every 15 s while nothing is
// followed: a reload, a re-opened tab or a browser that was already
// open when someone else started the update picks it up, and a
// just-finished one is announced once.

import { defineStore } from "pinia";
import { computed, ref, shallowRef } from "vue";

import type { CommandResult } from "../entities/common/CommandResult";
import type { UpdateStatus } from "../entities/system";
import { systemFacade } from "../facades/systemFacade";
import { useConsoleStore } from "./console";

const POLL_INTERVAL_MS = 2000;
/** Background check for an update started elsewhere, while none is followed. */
const IDLE_CHECK_MS = 15000;
/** System service unreachable this long → stop waiting, tell the operator. */
const UNREACHABLE_LIMIT_MS = 10 * 60 * 1000;
/** A finished update is announced on app start only if this recent. */
const ANNOUNCE_WINDOW_MS = 15 * 60 * 1000;
/** Run id that was already announced (per browser; a convenience only). */
const ANNOUNCED_KEY = "systemUpdate.announcedRunId";

export type UpdateMode = "idle" | "running" | "failed" | "unreachable";

function readAnnounced(): string | null {
  try {
    return window.localStorage.getItem(ANNOUNCED_KEY);
  } catch {
    return null;
  }
}

function writeAnnounced(runId: string): void {
  try {
    window.localStorage.setItem(ANNOUNCED_KEY, runId);
  } catch {
    // Storage unavailable — worst case the notification shows twice.
  }
}

async function reloadIntoNewBuild(): Promise<void> {
  // The PWA service worker (registerType: autoUpdate) would otherwise
  // serve the precached old bundle for this one navigation.
  try {
    const registration = await navigator.serviceWorker?.getRegistration();
    await registration?.update();
  } catch {
    // No service worker (dev) or the check failed — a plain reload still works.
  }
  window.location.reload();
}

export const useSystemUpdateStore = defineStore("systemUpdate", () => {
  const consoleStore = useConsoleStore();

  /** Run this browser is following (started here or picked up on resume). */
  const runId = ref<string | null>(null);
  /** Last status read for that run. */
  const status = shallowRef<UpdateStatus | null>(null);
  const mode = ref<UpdateMode>("idle");
  /** When the system service stopped answering (ms), `null` while it answers. */
  const unreachableSince = ref<number | null>(null);

  let timer: ReturnType<typeof setTimeout> | null = null;

  /** Overlay visible: an update is in progress or ended without success. */
  const isActive = computed(() => mode.value !== "idle");
  const isRunning = computed(() => mode.value === "running");

  function stopPolling(): void {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }

  function schedule(): void {
    stopPolling();
    timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
  }

  function scheduleIdleCheck(): void {
    stopPolling();
    timer = setTimeout(() => void resume(), IDLE_CHECK_MS);
  }

  function announce(finished: UpdateStatus): void {
    if (!finished.runId) return;
    writeAnnounced(finished.runId);
    if (finished.state === "done") {
      const version = finished.commitAfter ? ` (version ${finished.commitAfter})` : "";
      consoleStore.success(`System update finished${version}.`, {
        popup: true,
        title: "System update",
        lifetime: 15,
      });
    } else {
      consoleStore.error(
        `System update failed during '${finished.phase}': ${finished.message || "see update.log"}`,
        { popup: true, title: "System update", lifetime: null },
      );
    }
  }

  async function poll(): Promise<void> {
    const current = await systemFacade.fetchUpdateStatus();

    if (current === null) {
      // Expected while the update stops / rebuilds / restarts the service.
      unreachableSince.value ??= Date.now();
      if (Date.now() - unreachableSince.value > UNREACHABLE_LIMIT_MS) {
        mode.value = "unreachable";
        consoleStore.error(
          "System update: the system service has not come back for 10 minutes. Check update.log on the machine.",
          { popup: true, title: "System update", lifetime: null },
        );
        return;
      }
      schedule();
      return;
    }
    unreachableSince.value = null;

    // An older run's status (our run has not written yet) — keep waiting.
    if (current.runId !== runId.value) {
      schedule();
      return;
    }
    status.value = current;

    if (current.state === "running") {
      schedule();
      return;
    }
    if (current.state === "done") {
      // Announced by `resume()` after the reload, from the new build.
      await reloadIntoNewBuild();
      return;
    }
    // failed (or idle: the status vanished) — show it, stop waiting.
    mode.value = "failed";
    announce(current);
  }

  function follow(id: string): void {
    runId.value = id;
    mode.value = "running";
    unreachableSince.value = null;
    schedule();
  }

  /** Start an update and follow it. */
  async function start(): Promise<CommandResult> {
    const result = await systemFacade.triggerUpdate();
    if (!result.ok) {
      consoleStore.error(`Update failed to start: ${result.failureReason}`, { popup: true, title: "System update" });
      return result;
    }
    consoleStore.warning("System update started. The machine stops and the connection may drop.");
    follow(result.message);
    return result;
  }

  /**
   * At app start (and every 15 s while idle): pick up a running update,
   * announce a just-finished one.
   */
  async function resume(): Promise<void> {
    if (mode.value !== "idle") return;
    const current = await systemFacade.fetchUpdateStatus();
    if (current?.runId && current.isRunning) {
      status.value = current;
      follow(current.runId);
      return;
    }
    if (
      current?.runId &&
      current.isFinished &&
      readAnnounced() !== current.runId &&
      Date.now() - current.finishedAtMs < ANNOUNCE_WINDOW_MS
    ) {
      announce(current);
    }
    scheduleIdleCheck();
  }

  /** Close the overlay after a failure. */
  function dismiss(): void {
    mode.value = "idle";
    scheduleIdleCheck();
  }

  return {
    runId,
    status,
    mode,
    unreachableSince,
    isActive,
    isRunning,
    start,
    resume,
    dismiss,
  };
});
