// Single source of truth for translating the generated OpenAPI
// client's error shapes into a single operator-readable string.
//
// Three envelope shapes land in the frontend today (issue #99):
//
//   1. **Structured** — ``{ error: { section, key, line, message,
//      kind } }`` for compile-time validation failures (Pydantic
//      ``ConfigValidationError`` path).
//   2. **FastAPI default** — ``{ detail: "<string>" }`` for plain
//      ``HTTPException`` errors. ``detail`` is sometimes a list of
//      ``{ loc, msg, type }`` entries (Pydantic request validation).
//   3. **Plain Error** — any thrown ``Error`` whose ``.message`` is
//      already human-readable (rare, mostly native JS exceptions).
//
// Each backend call site historically re-implemented the
// interpreter; this module consolidates it. The contract is one
// function, one job, one place to add a new envelope shape.

import { useConsoleStore } from "../stores/console";
import type { CommandResult } from "../entities/common/CommandResult";

/**
 * Render any thrown error / fetch failure as a single
 * operator-readable sentence.
 *
 * The function is intentionally permissive — ``null`` / ``undefined``
 * / empty string round-trip to the empty string so callers can
 * coalesce without checking. Any object with a structured ``error``
 * envelope wins over the legacy FastAPI detail shapes, which wins
 * over the plain ``Error.message`` fallback.
 *
 * @param {unknown} error The thrown value (often an ``ApiError``
 *   from the generated OpenAPI client, sometimes a plain ``Error``,
 *   occasionally ``null``).
 * @returns {string} A single sentence. Empty when ``error`` is
 *   falsy.
 */
export function describeError(error: unknown): string {
  if (!error) return ""
  if (typeof error === "string") return error
  if (typeof error === "object") {
    const body = (error as { body?: unknown }).body
    if (body && typeof body === "object") {
      // Issue #99 structured envelope — the canonical path for
      // compile-time validation failures raised by the global
      // ``register_exception_handlers`` hook in
      // ``backend/modules/machineconfig/router.py``.
      const structured = (body as { error?: unknown }).error
      if (
        structured &&
        typeof structured === "object" &&
        typeof (structured as { message?: unknown }).message === "string"
      ) {
        return (structured as { message: string }).message
      }
      // FastAPI ``HTTPException(detail=<string>)`` shape.
      const detail = (body as { detail?: unknown }).detail
      if (Array.isArray(detail)) {
        return detail
          .map((d: { msg?: unknown }) =>
            typeof d.msg === "string" ? d.msg : JSON.stringify(d),
          )
          .join("; ")
      }
      if (
        detail &&
        typeof detail === "object" &&
        typeof (detail as { message?: unknown }).message === "string"
      ) {
        return (detail as { message: string }).message
      }
      if (typeof detail === "string") return detail
    }
  }
  if (error instanceof Error) return error.message
  return String(error)
}

/**
 * Convenience form: like :func:`describeError` but always returns a
 * non-empty string, falling back to the supplied default. Useful at
 * the call site when the caller wants to log "something" without
 * having to check for empty.
 *
 * @param {unknown} error
 * @param {string} fallback Default value when the formatter yields
 *   an empty string. Defaults to ``"Unknown error"`` to mirror the
 *   legacy call sites.
 */
export function describeErrorOr(error: unknown, fallback: string = "Unknown error"): string {
  const text = describeError(error)
  return text || fallback
}

/**
 * Extract the HTTP status code carried by a generated-client
 * ``ApiError``. Returns ``null`` when the value is not a recognised
 * API error envelope — native ``Error``s, ``null``, primitives, and
 * network failures with no response all collapse to ``null`` so
 * ``CommandResult`` callers can branch on the canonical signal
 * without sprinkling type guards.
 *
 * @param {unknown} error
 * @returns {number | null}
 */
export function errorStatus(error: unknown): number | null {
  if (!error || typeof error !== "object") return null
  const status = (error as { status?: unknown }).status
  return typeof status === "number" ? status : null
}

/**
 * Uniform failure reporter for every manual user action.
 *
 * The legacy pattern was a hand-rolled ``consoleStore.error(`Failed
 * to <name>: ${err.message}`)`` at every call site — the messages
 * drifted over time (some prefixed with ``[ToolStore]``, some used
 * ``err.body?.detail``, some missed the trailing period, none fired
 * a toast). This helper is the single chokepoint.
 *
 * Message shape:
 *
 *   ``"<name> failed (HTTP <code>): <reason>"`` when a status code
 *   is present;
 *
 *   ``"<name> failed: <reason>"`` otherwise (WebSocket fire-and-
 *   forget, native ``Error``s without an HTTP envelope).
 *
 * Always routes through ``consoleStore.error(text, { popup: true })``
 * so a toast fires; the operator does not need to be looking at
 * the console pane when an action fails.
 *
 * Stores call this on ``result.failed`` after their facade call;
 * Vue components do not need to import it directly.
 *
 * @param {string} name Operator-friendly label of the action
 *   (e.g. ``"home axis 0"``, ``"start program"``, ``"deploy"``).
 * @param {CommandResult} result The ``CommandResult`` returned by
 *   the facade that performed the dispatch.
 */
export function reportCommandFailure(name: string, result: CommandResult): void {
  const status =
    result.statusCode != null ? ` (HTTP ${result.statusCode})` : ""
  const reason =
    result.failureReason == null
      ? "unknown error"
      : typeof result.failureReason === "string"
        ? result.failureReason
        : String(result.failureReason)
  useConsoleStore().error(`${name} failed${status}: ${reason}`, {
    popup: true,
  })
}

export default describeError
