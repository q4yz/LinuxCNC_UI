// Frontend HTTP client for the macro subsystem (issue #7).
//
// The hand-rolled wrapper keeps the call sites short and stable
// while the backend stays open to refactor. The endpoints map
// 1:1 to ``backend/routers/macros.py``:
//
//   GET    /api/macros          -> listMacros()
//   GET    /api/macros/{name}   -> getMacro(name)
//   PUT    /api/macros/{name}   -> saveMacro(name, content)
//   DELETE /api/macros/{name}   -> deleteMacro(name)
//   POST   /api/macros/{name}/run -> runMacro(name)
//
// Errors are surfaced as a thrown ``Error`` with a human-readable
// message so the Pinia store can render the failure in the editor
// console without having to re-parse the structured payload.

const BASE = '/api/macros';

async function handle(response) {
  if (response.ok) {
    return response.json();
  }
  let detail = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    if (body && typeof body.detail === 'string') {
      detail = body.detail;
    }
  } catch (_) {
    // Body is not JSON; keep the status / statusText.
  }
  throw new Error(detail);
}

export async function listMacros() {
  const response = await fetch(BASE, { method: 'GET' });
  return handle(response);
}

export async function getMacro(name) {
  const encoded = encodeURIComponent(name);
  const response = await fetch(`${BASE}/${encoded}`, { method: 'GET' });
  return handle(response);
}

export async function saveMacro(name, content) {
  const encoded = encodeURIComponent(name);
  const response = await fetch(`${BASE}/${encoded}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  return handle(response);
}

export async function deleteMacro(name) {
  const encoded = encodeURIComponent(name);
  const response = await fetch(`${BASE}/${encoded}`, { method: 'DELETE' });
  return handle(response);
}

export async function runMacro(name) {
  const encoded = encodeURIComponent(name);
  const response = await fetch(`${BASE}/${encoded}/run`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  });
  return handle(response);
}
