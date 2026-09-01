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

  // Vite dev (5173), vite preview (4173), standard HTTP/HTTPS (empty string, 80, 443),
  // and the Nginx HTTPS appliance port (8080) all proxy `/api` to the backend.
  // Leaving BASE empty keeps requests on the same origin, avoiding CORS and
  // mixed-content blocks.
  const isReverseProxied =
    port === '' ||
    port === '80' ||
    port === '443' ||
    port === '8080' ||
    port === '5173' ||
    port === '4173';

  if (isReverseProxied) {
    return '';
  }

  // Fallback for raw development setups (like running raw on Windows without Nginx)
  // where the frontend isn't proxying API requests and must hit uvicorn directly.
  return `${protocol}//${hostname}:8000`;
})();

OpenAPI.BASE = configuredBase;

export { OpenAPI };