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
//
// Raw ``fetch`` instead of the generated client: ``generated/api/``
// is regenerated from the live backends and still carries the old
// ``profile``-based switch contract; these routes gained the
// ``machine`` body afterwards. When the client is next regenerated
// these four functions can migrate onto
// ``SystemMachineLifecycleService`` unchanged.

export interface MachineStatus {
  running: boolean;
  pids: number[];
  /** Deprecated alias of ``default_machine`` (generated-model compat). */
  machine_name: string | null;
  default_machine: string | null;
  ini_path: string | null;
  ini_exists: boolean;
  started_pid?: number | null;
}

/**
 * JSON request with FastAPI error surfacing: the ``detail`` string
 * becomes the Error message and the HTTP status is attached as
 * ``err.status`` so callers can special-case 404 / 409.
 */
async function machineRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch (err: unknown) {
    // Network-level failure (system service unreachable).
    throw Object.assign(
      new Error(
        `Machine lifecycle request failed: ${err instanceof Error ? err.message : String(err)}`,
      ),
      { status: 0 },
    );
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body — keep the generic message.
    }
    throw Object.assign(new Error(detail), { status: response.status });
  }

  return (await response.json()) as T;
}

export class MachineLifecycleFacade {
  static getStatus(): Promise<MachineStatus> {
    return machineRequest<MachineStatus>("/api/v1/system/machine");
  }

  static startMachine(machine?: string): Promise<MachineStatus> {
    return machineRequest<MachineStatus>("/api/v1/system/machine/start", {
      method: "POST",
      body: JSON.stringify(machine ? { machine } : {}),
    });
  }

  static setDefaultMachine(machine: string): Promise<MachineStatus> {
    return machineRequest<MachineStatus>("/api/v1/system/machine/default", {
      method: "POST",
      body: JSON.stringify({ machine }),
    });
  }

  static stopMachine(): Promise<MachineStatus> {
    return machineRequest<MachineStatus>("/api/v1/system/machine/stop", {
      method: "POST",
    });
  }
}

export default MachineLifecycleFacade;
