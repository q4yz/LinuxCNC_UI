// Runtime configuration for the generated OpenAPI client.
//
// The generator emits a fully typed client under `./api`, but leaves `OpenAPI.BASE`
// as an empty string so the generated URLs are relative (e.g. `/api/v1/...`). To keep
// parity with the previous hand-written client — which targeted the FastAPI backend on
// port 8000 of the page's hostname — this module wires `OpenAPI.BASE` to that same
// origin on import. Side-effecting the import once from the app entry-point is
// sufficient; service classes read `OpenAPI` lazily at request time.

import { OpenAPI } from '../../generated/api/core/OpenAPI';

const configuredBase = (() => {
  if (typeof window === 'undefined') {
    return '';
  }
  const { protocol, hostname } = window.location;
  // Vite dev server proxies `/api` to the FastAPI backend, so leaving BASE empty in
  // dev keeps everything on the same origin and avoids CORS. In any other
  // deployment, fall back to the explicit backend origin on port 8000.
  const isViteDevHost = hostname === 'localhost' || hostname === '127.0.0.1';
  if (isViteDevHost) {
    return '';
  }
  return `${protocol}//${hostname}:8000`;
})();

OpenAPI.BASE = configuredBase;

export { OpenAPI };
