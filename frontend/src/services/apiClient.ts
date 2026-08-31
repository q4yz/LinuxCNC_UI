// Runtime configuration for the generated OpenAPI client.
//
// The generator emits a fully typed client under `./api`, but leaves `OpenAPI.BASE`
// as an empty string so the generated URLs are relative (e.g. `/api/v1/...`). To keep
// parity with the previous hand-written client — which targeted the FastAPI backend on
// port 8000 of the page's hostname — this module wires `OpenAPI.BASE` to that same
// origin on import. Side-effecting the import once from the app entry-point is
// sufficient; service classes read `OpenAPI` lazily at request time.

import { OpenAPI } from '../../generated/api';

const configuredBase = (() => {
  if (typeof window === 'undefined') {
    return '';
  }
  const { protocol, hostname, port } = window.location;
  // Vite dev (5173) and vite preview (4173) both proxy `/api` and `/ws`
  // to the FastAPI backend on localhost:8000, so leaving BASE empty keeps
  // everything on the same origin and avoids CORS / mixed-content.
  const isViteServed = port === '5173' || port === '4173';
  if (isViteServed) {
    return '';
  }
  return `${protocol}//${hostname}:8000`;
})();

OpenAPI.BASE = configuredBase;

export { OpenAPI };
