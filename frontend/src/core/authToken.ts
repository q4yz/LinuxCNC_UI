// The session token of the logged-in account (#131), kept on this
// device so a login lasts (the token does not expire; the backend ends
// it on a password change or "log out everywhere"). Read by every
// request: the generated client (``services/apiClient``) and the
// WebSockets (``withToken``). No token = a viewer.

const KEY = "linuxcnc-ui.session-token";
type Listener = (token: string | null) => void;
const listeners = new Set<Listener>();

let memory: string | null = null;

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  try {
    return storage()?.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

export function setToken(token: string | null): void {
  memory = token;
  try {
    if (token) storage()?.setItem(KEY, token);
    else storage()?.removeItem(KEY);
  } catch {
    // private window: the login lasts for this page only
  }
  for (const listener of listeners) listener(token);
}

/** Called when the token changes (login, logout): sockets reconnect with it. */
export function onTokenChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** A WebSocket URL with the token (browsers cannot send headers there). */
export function withToken(url: string): string {
  const token = getToken();
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}access_token=${encodeURIComponent(token)}`;
}
