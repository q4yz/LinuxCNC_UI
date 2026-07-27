// Thin fetch wrapper for the ``machineconfig`` backend module.
//
// The OpenAPI codegen produces one TS class per backend router, but
// rebuilding that artifact requires a live backend and is not part of
// the standard ``npm ci`` flow (see
// ``frontend/scripts/generate-api.mjs`` — install mode just warns).
// For the new module we use plain ``fetch`` calls instead so the
// build does not depend on a freshly regenerated client.
//
// The wrapper targets the module-scoped URLs:
//
//   /api/v1/modules/machineconfig/...
//
// which are mounted by :class:`MachineConfigModule` in
// ``backend/modules/machineconfig/module.py``. ``apiBase()`` returns
// the same origin the page is served from so the Vite dev-server
// ``/api`` proxy and the prod reverse-proxy both keep working
// unchanged.

const MODULE_PREFIX = "/api/v1/modules/machineconfig";

function apiBase() {
  if (typeof window === "undefined") return "";
  const { protocol, hostname } = window.location;
  // The Vite dev server proxies ``/api`` to the FastAPI backend on
  // port 8000 — leaving the BASE empty keeps everything on the same
  // origin and avoids CORS in dev. In any other deployment, fall back
  // to the explicit backend origin on port 8000 so the production
  // stack still works.
  const isViteDevHost = hostname === "localhost" || hostname === "127.0.0.1";
  if (isViteDevHost) return "";
  return `${protocol}//${hostname}:8000`;
}

async function request(path, { method = "GET", body, headers } = {}) {
  const hasFormData = typeof FormData !== "undefined" && body instanceof FormData;
  const response = await fetch(`${apiBase()}${path}`, {
    method,
    headers: {
      ...(hasFormData ? {} : { "Content-Type": "application/json" }),
      ...(headers || {}),
    },
    body: body !== undefined ? (hasFormData ? body : JSON.stringify(body)) : undefined,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      if (payload && payload.detail) {
        detail = Array.isArray(payload.detail)
          ? payload.detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
          : payload.detail;
      }
    } catch {
      // The body wasn't JSON; keep the HTTP status text.
    }
    const err = new Error(detail);
    err.status = response.status;
    throw err;
  }
  // 204 No Content short-circuit (the registry rarely uses this but
  // future-proofing is cheap).
  if (response.status === 204) return null;
  return response.json();
}

// ----------------------------------------------------------------- //
// Compilers                                                            //
// ----------------------------------------------------------------- //

export function listCompilers() {
  return request(`${MODULE_PREFIX}/compilers`);
}

// ----------------------------------------------------------------- //
// Profiles CRUD                                                        //
// ----------------------------------------------------------------- //

export function listProfilesTree() {
  return request(`${MODULE_PREFIX}/profiles/tree`);
}

export function readProfile(path) {
  return request(
    `${MODULE_PREFIX}/profiles/content/${encodeURI(path)}`,
  );
}

export function saveProfile(path, content) {
  return request(`${MODULE_PREFIX}/profiles/content/${encodeURI(path)}`, {
    method: "PUT",
    body: { content },
  });
}

export function createFolder(path) {
  return request(`${MODULE_PREFIX}/profiles/folder`, {
    method: "POST",
    body: { path },
  });
}

export function createFile(path) {
  return request(`${MODULE_PREFIX}/profiles/file`, {
    method: "POST",
    body: { path },
  });
}

export function renameProfile(source, destination) {
  return request(`${MODULE_PREFIX}/profiles/rename`, {
    method: "PUT",
    body: { source, destination },
  });
}

export function uploadProfile(path, file) {
  const form = new FormData();
  form.append("file", file);
  return request(`${MODULE_PREFIX}/profiles/upload/${encodeURI(path)}`, {
    method: "POST",
    body: form,
  });
}

export function deleteProfile(path) {
  return request(
    `${MODULE_PREFIX}/profiles/${encodeURI(path)}`,
    { method: "DELETE" },
  );
}

// ----------------------------------------------------------------- //
// Compile / Deploy                                                      //
// ----------------------------------------------------------------- //

export function compileProfile(profilePath, compilerId) {
  return request(`${MODULE_PREFIX}/compile`, {
    method: "POST",
    body: { profile_path: profilePath, compiler_id: compilerId },
  });
}

export function deployStaged({ confirmFlash }) {
  return request(`${MODULE_PREFIX}/deploy`, {
    method: "POST",
    body: { confirm_flash: confirmFlash },
  });
}

// ----------------------------------------------------------------- //
// Staged / Active (read-only)                                           //
// ----------------------------------------------------------------- //

export function listStaged() {
  return request(`${MODULE_PREFIX}/staged`);
}

export function readStagedContent(name) {
  return request(
    `${MODULE_PREFIX}/staged/content/${encodeURI(name)}`,
  );
}

export function listActive() {
  return request(`${MODULE_PREFIX}/active`);
}

export function readActiveContent(name) {
  return request(
    `${MODULE_PREFIX}/active/content/${encodeURI(name)}`,
  );
}

export function readMachineName() {
  return request(`${MODULE_PREFIX}/machine-name`);
}