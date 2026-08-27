// Frontend settings client wrapper around the four canonical
// endpoints. Hand-rolled ``fetch`` (not the generated OpenAPI
// client) so modules keep working when ``generated/api/`` is stale.
// See ``.agent/STATE.md`` § 5.

const API_PREFIX = "/api/v1/modules";

/**
 * Build a settings client scoped to one module.
 *
 * @param {string} moduleId
 */
export function createModuleSettings(moduleId: string) {
  if (!moduleId) throw new Error("createModuleSettings: moduleId is required");
  const base = `${API_PREFIX}/${moduleId}/settings`;

  async function jsonRequest(method: string, url: string, body?: unknown): Promise<unknown> {
    const init: RequestInit = {
      method,
      headers: { "Content-Type": "application/json" },
    };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
    }
    const res = await fetch(url, init);
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const payload = await res.json();
        detail = payload?.detail ?? detail;
      } catch (_) {
        // Body wasn't JSON; fall back to status text.
      }
      throw new Error(`Settings ${method} ${url} failed: ${res.status} ${detail}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  return {
    /** Read all settings for this module. */
    async readAll(): Promise<Record<string, unknown>> {
      const result = await jsonRequest("GET", base);
      if (result && typeof result === "object" && !Array.isArray(result)) {
        return result as Record<string, unknown>;
      }
      return {};
    },

    /** Read a single settings key. Throws on 404. */
    async readKey(key: string): Promise<unknown> {
      const data = await jsonRequest(
        "GET",
        `${base}/${encodeURIComponent(key)}`,
      );
      if (data && typeof data === "object" && !Array.isArray(data)) {
        return (data as Record<string, unknown>)[key];
      }
      return undefined;
    },

    /** Replace the entire settings payload. Returns the merged payload. */
    async writeAll(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
      const result = await jsonRequest("PUT", base, payload);
      if (result && typeof result === "object" && !Array.isArray(result)) {
        return result as Record<string, unknown>;
      }
      return {};
    },

    /** Upsert a single key. Returns the merged payload. */
    async writeKey(key: string, value: unknown): Promise<Record<string, unknown>> {
      const result = await jsonRequest(
        "PUT",
        `${base}/${encodeURIComponent(key)}`,
        value,
      );
      if (result && typeof result === "object" && !Array.isArray(result)) {
        return result as Record<string, unknown>;
      }
      return {};
    },
  };
}

export default createModuleSettings;