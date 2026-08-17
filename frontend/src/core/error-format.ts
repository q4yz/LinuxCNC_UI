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
export function describeError(error) {
  if (!error) return ""
  if (typeof error === "string") return error
  if (typeof error === "object") {
    const body = error.body
    if (body && typeof body === "object") {
      // Issue #99 structured envelope — the canonical path for
      // compile-time validation failures raised by the global
      // ``register_exception_handlers`` hook in
      // ``backend/modules/machineconfig/router.py``.
      const structured = body.error
      if (
        structured &&
        typeof structured === "object" &&
        typeof structured.message === "string"
      ) {
        return structured.message
      }
      // FastAPI ``HTTPException(detail=<string>)`` shape.
      const detail = body.detail
      if (Array.isArray(detail)) {
        return detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
      }
      if (
        detail &&
        typeof detail === "object" &&
        typeof detail.message === "string"
      ) {
        return detail.message
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
export function describeErrorOr(error, fallback = "Unknown error") {
  const text = describeError(error)
  return text || fallback
}

export default describeError
