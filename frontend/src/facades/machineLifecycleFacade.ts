// Machine lifecycle facade — LinuxCNC session control via the
// always-up system service (:8001).
//
// Wraps ``/api/v1/system/machine`` (see
// ``backend/system/routers/machine_lifecycle.py``):
//
//   * ``getMachineStatus()``  — session running? which machine is
//     the persisted default? does its INI exist?
//   * ``startMachine(machine?)`` — start the session. With a
//     machine name that machine is persisted as the default ("start
//     implies main") and its ``machines/<name>/config/machine.ini``
//     is launched; without one the persisted default starts (404
//     when none selected). 409 when already running.
//   * ``setDefaultMachine(machine)`` — "Select as main": persist the
//     default without starting anything.
//   * ``stopMachine()`` — SIGINT → SIGTERM → SIGKILL, idempotent.
//   * ``getConsoleLog(lines?)`` — tail of LinuxCNC's own logs plus the
//     system service's, every line tagged "LinuxCNC: " / "UI: ", so the
//     UI can show why a session crashed without shell access.
//
// On the generated ``SystemMachineLifecycleService``; failures keep the
// shape callers rely on: an ``Error`` whose message is the backend's
// ``detail`` and whose ``status`` is the HTTP status (0: unreachable).

import { SystemMachineLifecycleService } from "../../generated/api/services/SystemMachineLifecycleService";
import { describeError, errorStatus } from "../core/error-format";

/** Session state reported by the system service. */
export type MachineSessionState = "stopped" | "starting" | "running" | "stopping";

export interface MachineStatus {
  /** Absent on a system service older than the state field. */
  state?: MachineSessionState;
  running: boolean;
  /**
   * ``ui``: the session runs one of this UI's machine INIs (and so its
   * machine backend); ``external``: LinuxCNC started elsewhere with
   * another INI — this UI cannot talk to it. ``null`` when stopped.
   */
  owner?: "ui" | "external" | null;
  /** INI the running session was started with, if readable. */
  running_ini?: string | null;
  pids: number[];
  /** Deprecated alias of ``default_machine`` (generated-model compat). */
  machine_name: string | null;
  default_machine: string | null;
  ini_path: string | null;
  ini_exists: boolean;
  started_pid?: number | null;
}

export interface MachineConsoleLog {
  path: string;
  exists: boolean;
  log: string;
}

/**
 * The call's result; a failure becomes ``Error(detail)`` with ``status``
 * (the HTTP status, 0 when the system service did not answer) so callers
 * can special-case 404 / 409 and show the backend's reason.
 */
async function lifecycle<T>(call: () => Promise<unknown>): Promise<T> {
  try {
    return (await call()) as T;
  } catch (err: unknown) {
    const status = errorStatus(err);
    const message = status === null
      ? `Machine lifecycle request failed: ${err instanceof Error ? err.message : String(err)}`
      : describeError(err);
    throw Object.assign(new Error(message), { status: status ?? 0 });
  }
}

export const machineLifecycleFacade = {
  getStatus: (): Promise<MachineStatus> =>
    lifecycle(() => SystemMachineLifecycleService.getMachineSessionStatus()),

  startMachine: (machine?: string): Promise<MachineStatus> =>
    lifecycle(() => SystemMachineLifecycleService.startMachineSession(machine ? { machine } : {})),

  setDefaultMachine: (machine: string): Promise<MachineStatus> =>
    lifecycle(() => SystemMachineLifecycleService.setDefaultMachine({ machine })),

  stopMachine: (): Promise<MachineStatus> =>
    lifecycle(() => SystemMachineLifecycleService.stopMachineSession()),

  getConsoleLog: (lines = 200): Promise<MachineConsoleLog> =>
    lifecycle(() => SystemMachineLifecycleService.getMachineConsoleLog(lines)),
};

export default machineLifecycleFacade;
