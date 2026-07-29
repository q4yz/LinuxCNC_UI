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
export function createModuleSettings(moduleId) {
  if (!moduleId) throw new Error("createModuleSettings: moduleId is required");
  const base = `${API_PREFIX}/${moduleId}/settings`;

  async function jsonRequest(method, url, body) {
    const init = {
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
    async readAll() {
      return (await jsonRequest("GET", base)) ?? {};
    },

    /** Read a single settings key. Throws on 404. */
    async readKey(key) {
      const data = await jsonRequest(
        "GET",
        `${base}/${encodeURIComponent(key)}`,
      );
      return data?.[key];
    },

    /** Replace the entire settings payload. Returns the merged payload. */
    async writeAll(payload) {
      return (await jsonRequest("PUT", base, payload)) ?? {};
    },

    /** Upsert a single key. Returns the merged payload. */
    async writeKey(key, value) {
      return (
        (await jsonRequest("PUT", `${base}/${encodeURIComponent(key)}`, value)) ??
        {}
      );
    },
  };
}

export default createModuleSettings;