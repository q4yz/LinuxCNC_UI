// Tests for the HTTP/HTTPS configuration banner that ships on the new
// Config page (``/config``). Behavioural tests live in the manual QA
// matrix in ``README.md``; here we lock the public contract that the
// nginx install path (``install.sh``) and the rest of the frontend
// depend on:
//
//   * The banner only renders when the SPA is loaded over plain HTTP.
//   * It never persists state (no localStorage / sessionStorage) so a
//     cleared cache cannot strand the operator on HTTP without the
//     prompt.
//   * The download link targets ``/cnc-root.crt`` — the path the
//     ``install.sh`` nginx block serves on port 80.
//   * The HTTPS switch link targets the same hostname under
//     ``https://`` so the operator lands on the secure origin with
//     the same deep-link intact.
//   * ``ConfigView`` actually mounts the banner.
//   * The router registers ``/config``.
//   * The sidebar has not been polluted with a config entry (this
//     page is route-only by design).

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const bannerPath = resolve(repoRoot, "frontend/src/components/HttpsBanner.vue");
const configViewPath = resolve(repoRoot, "frontend/src/views/ConfigView.vue");
const routerPath = resolve(repoRoot, "frontend/src/router/index.ts");
const sidebarPath = resolve(repoRoot, "frontend/src/components/AppSidebar.vue");

function read(path) {
  return readFileSync(path, "utf-8");
}

const banner = read(bannerPath);
const configView = read(configViewPath);
const router = read(routerPath);
const sidebar = read(sidebarPath);

// ---------------------------------------------------------------- //
// HttpsBanner.vue                                                    //
// ---------------------------------------------------------------- //

test("HttpsBanner only renders over plain HTTP", () => {
  // The banner is a noisy yellow callout — it must self-hide on
  // HTTPS so the operator who already trusts the cert doesn't see
  // it on every page load. The render gate reads the runtime
  // protocol (computed from ``window.location.protocol``).
  assert.match(
    banner,
    /window\.location\.protocol\s*===\s*['"]http:['"]/,
    "banner should gate render on http: protocol",
  );
  assert.match(banner, /v-if="visible"/);
});

test("HttpsBanner does not persist dismiss state", () => {
  // The banner re-appears on every HTTP visit by product decision;
  // asserting the absence of storage APIs is the regression guard.
  assert.doesNotMatch(banner, /localStorage/);
  assert.doesNotMatch(banner, /sessionStorage/);
  // The only piece of state the banner owns is the per-mount
  // dismiss flag — a plain ``ref(false)``.
  assert.match(banner, /const\s+dismissed\s*=\s*ref\(false\)/);
});

test("HttpsBanner links the download CTA to /cnc-root.crt", () => {
  // nginx serves the local CA at this exact path (see
  // ``install.sh``: ``location = /cnc-root.crt``) with
  // ``Content-Disposition: attachment``. The download attribute
  // hints to the browser to save rather than navigate.
  assert.match(banner, /href="\/cnc-root\.crt"/);
  assert.match(banner, /download=/);
});

test("HttpsBanner HTTPS switch targets the same hostname under https://", () => {
  // Mirrors the operator's current path so a deep link still
  // works after switching protocols.
  assert.match(banner, /`https:\/\/\$\{hostname\}/);
  assert.match(banner, /data-test="https-banner-switch"/);
});

test("HttpsBanner exposes a dismiss control with an accessible label", () => {
  // The close cross is a plain button so screen-reader and keyboard
  // users can hide the banner just like sighted users.
  assert.match(banner, /<button/);
  assert.match(banner, /aria-label="Dismiss banner"/);
  assert.match(banner, /data-test="https-banner-close"/);
});

test("HttpsBanner uses a yellow background", () => {
  // The yellow palette is the product requirement — operators
  // must spot the callout immediately on a dark UI.
  assert.match(banner, /bg-yellow-400/);
});

// ---------------------------------------------------------------- //
// ConfigView.vue                                                     //
// ---------------------------------------------------------------- //

test("ConfigView mounts the HttpsBanner", () => {
  assert.match(configView, /import\s+HttpsBanner\s+from/);
  assert.match(configView, /<HttpsBanner\s*\/>/);
});

// The detailed per-platform (Android/iOS/Desktop) root-CA install
// walkthrough that used to live inline in ConfigView.vue was
// removed — HttpsBanner.vue's own download-the-cert CTA (already
// covered by "HttpsBanner links the download CTA to /cnc-root.crt"
// above) is the entire feature now. There's no separate install
// guide left anywhere in the codebase to pin.

// ---------------------------------------------------------------- //
// router/index.ts                                                    //
// ---------------------------------------------------------------- //

test("router registers the /config route", () => {
  // Route-only entry — no sidebar link. ``name`` is what other
  // code uses to push the route via ``router.push({ name: 'config' })``.
  assert.match(router, /path:\s*['"]\/config['"]/);
  assert.match(router, /name:\s*['"]config['"]/);
  assert.match(router, /component:\s*ConfigView/);
});

// ---------------------------------------------------------------- //
// AppSidebar.vue (regression guard)                                  //
// ---------------------------------------------------------------- //

test("AppSidebar exposes a config entry", () => {
  // ConfigView.vue was repurposed from a niche HTTPS-setup helper
  // into the primary machine-config management page (profiles,
  // machines, macros, m-codes, active-config panel) — it earns a
  // direct sidebar link now rather than staying route-only.
  assert.match(sidebar, /id:\s*['"]config['"]/);
});
