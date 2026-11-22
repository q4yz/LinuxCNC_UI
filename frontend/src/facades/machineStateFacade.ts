// Machine-state facade. UI-facing API for machine-state reads +
// writes (set state, set mode, send MDI line, home axis).
//
// Reads piggyback on the existing ``stores/stateFacade.js`` (which
// owns the WebSocket transport). Writes go through the generated
// ``ModulesMachineStateService`` + ``ModulesAxisService`` and always
// return a ``CommandResult`` so the store / component layer can
// route through ``reportCommandFailure`` uniformly.

import {
  ModulesMachineStateService,
} from "../../generated/api/services/ModulesMachineStateService";
import { ModulesAxisService } from "../../generated/api/services/ModulesAxisService";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";

async function _commandResultFrom(
  promise: Promise<unknown>,
  commandId: string,
): Promise<CommandResult> {
  try {
    await promise;
    return CommandResult.success({ commandId });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId,
      statusCode: errorStatus(err),
    });
  }
}

async function setState(state: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineStateService.setMachineState({ state }),
    `set-state:${state}`,
  );
}

/**
 * Critical e-stop activation.
 *
 * Drives ``halui.estop.activate`` directly via HAL, bypassing the NML
 * command channel for the fastest possible operator reaction (~1 ms
 * servo-thread latency instead of the ~100-300 ms NML round-trip).
 *
 * Used exclusively by the global E-Stop header button
 * (``EStopHeader.vue``). The state bar's smaller E-STOP button still
 * calls :func:`setState` so the two affordances keep distinct
 * contracts.
 *
 * The backend fails hard: any HAL write failure surfaces as a
 * ``CommandResult.failure`` (HTTP 503) without falling back to the
 * slow NML path.
 */
async function activateEstop(): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineStateService.activateEstop(),
    "estop:activate",
  );
}

async function setMode(mode: 1 | 2 | 3 | 4): Promise<CommandResult> {
  // The generated client types ``_ModeCommand.mode`` as ``string``
  // (the backend accepts "manual" / "auto" / "mdi") while this
  // facade's historical contract accepted numeric literals. Cast
  // at the seam so the public API stays intact; nobody calls this
  // function today so the mismatch is dormant.
  return _commandResultFrom(
    ModulesMachineStateService.setMachineMode({ mode: mode as unknown as string }),
    `set-mode:${mode}`,
  );
}

async function sendMdi(line: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineStateService.runMdiCommand({ command: line }),
    "mdi",
  );
}

/**
 * Home a single axis by letter (``"x"|"y"|"z"``) or every axis when
 * ``axis === "all"``. The wire contract carries the canonical
 * LinuxCNC letter end-to-end so the backend can do the
 * ``letter → joint id(s)`` lookup without an index translation
 * layer.
 */
async function setHomeAxis(axis: "x" | "y" | "z" | "all"): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesAxisService.homeAxis({ axis }),
    axis === "all" ? "home:all" : `home:${axis}`,
  );
}

/** What ``/api/v1/health`` says about the machine backend. */
export interface MachineHealth {
  linuxcncConnected: boolean;
  shuttingDown: boolean;
}

/**
 * The machine backend's reachability probe: its health, or ``null`` for
 * any non-200 (e.g. a 502 from the proxy while it is down); throws on a
 * timeout or network error.
 *
 * A raw ``fetch`` on purpose (the one in a facade): the generated
 * ``DefaultService.health`` cannot time out or skip the HTTP cache, and a
 * heartbeat needs both.
 */
async function health(timeoutMs: number): Promise<MachineHealth | null> {
  const response = await fetch("/api/v1/health", {
    method: "GET",
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) return null;
  const body = (await response.json().catch(() => ({}))) as {
    linuxcnc_connected?: unknown;
    shutting_down?: unknown;
  };
  // An older backend without the fields is treated as connected.
  return {
    linuxcncConnected: body.linuxcnc_connected !== false,
    shuttingDown: body.shutting_down === true,
  };
}

export const machineStateFacade = Object.freeze({
  health,
  setState,
  setMode,
  sendMdi,
  setHomeAxis,
  activateEstop,
});

export default machineStateFacade;
