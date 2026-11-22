// Base-thread facade: the 1 Hz snapshot (``GET /api/v1/base-thread/snapshot``)
// mapped into a typed ``Snapshot``.

import { BaseThreadService } from "../../generated/api/services/BaseThreadService";
import { Snapshot } from "../entities/baseThread/Snapshot";
import { toSnapshot } from "../mappers/baseThreadMapper";

/**
 * The latest snapshot. A failure is logged and rethrown: the store owns
 * the error state rather than getting a half-built object.
 */
async function fetchSnapshot(): Promise<Snapshot> {
  try {
    return toSnapshot(await BaseThreadService.getBaseThreadSnapshot());
  } catch (err: unknown) {
    console.error("[baseThreadFacade] Failed to fetch snapshot", err);
    throw err;
  }
}

/**
 * The STATIC tier only (``?mode=static``) — configuration baked into
 * ``hardware.json`` (axis travel limits, joint numbers, ...) that the
 * backend caches for the session. Every dynamic field comes back
 * null / omitted; ``toSnapshot`` defaults them.
 */
async function fetchStatic(): Promise<Snapshot> {
  try {
    return toSnapshot(await BaseThreadService.getBaseThreadSnapshot("static"));
  } catch (err: unknown) {
    console.error("[baseThreadFacade] Failed to fetch static snapshot", err);
    throw err;
  }
}

export const baseThreadFacade = Object.freeze({ fetchSnapshot, fetchStatic });

export default baseThreadFacade;
