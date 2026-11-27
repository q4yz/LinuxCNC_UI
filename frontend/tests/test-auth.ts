// #131: the session token rides on every request; the account control
// offers setup / login / logout; admins manage users.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");
const read = (p: string) => readFileSync(resolve(src, p), "utf-8");

test("runtime: the token is stored, announced and put on WebSocket URLs", async () => {
  const store = new Map<string, string>();
  (globalThis as any).window ??= globalThis;
  (globalThis as any).window.localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
  const { getToken, setToken, onTokenChange, withToken } = await import(pathToFileURL(resolve(src, "core/authToken.ts")).href);
  const seen: (string | null)[] = [];
  onTokenChange((t: string | null) => seen.push(t));

  assert.equal(withToken("ws://h/ws/telemetry"), "ws://h/ws/telemetry");
  setToken("a.b c");
  assert.equal(getToken(), "a.b c");
  assert.equal(withToken("ws://h/ws/telemetry"), "ws://h/ws/telemetry?access_token=a.b%20c");
  assert.equal(withToken("ws://h/x?y=1"), "ws://h/x?y=1&access_token=a.b%20c");
  setToken(null);
  assert.equal(getToken(), null);
  assert.deepEqual(seen, ["a.b c", null]);
});

test("every request carries the token: the generated client and both sockets", () => {
  assert.match(read("services/apiClient.ts"), /OpenAPI\.TOKEN = async \(\) => getToken\(\) \?\? ''/);
  assert.match(read("facades/servoThreadFacade.ts"), /new WebSocket\(withToken\(/);
  assert.match(read("facades/servoThreadFacade.ts"), /onTokenChange\(\(\) => servoThreadFacade\.reconnectWithNewToken\(\)\)/);
  assert.match(read("facades/servoThreadFacade.ts"), /case 'denied':/);
  assert.match(read("facades/halScopeFacade.ts"), /new WebSocket\(withToken\(socketUrl\(\)\)\)/);
});

test("the account control: log in / out, the default password is flagged", () => {
  const menu = read("components/account/AccountMenu.vue");
  assert.match(menu, /if \(!auth\.authenticated\) dialog\.value = "login"/);
  assert.match(menu, /default password!/);
  assert.doesNotMatch(read("stores/authStore.ts"), /needsSetup|setup\(/);
  assert.match(read("components/AppSidebar.vue"), /<AccountMenu :collapsed="isCollapsed" \/>/);
  // a token the backend no longer takes is dropped
  assert.match(read("stores/authStore.ts"), /getToken\(\) && !current\.authenticated\) \{[\s\S]*?setToken\(null\)/);
});

test("admins get the Users tab", () => {
  const view = read("views/SettingsView.vue");
  assert.match(view, /auth\.authenticated && auth\.can\("users\.manage"\) \? \[USERS_TAB\]/);
  assert.match(view, /<UsersPanel \/>/);
});
