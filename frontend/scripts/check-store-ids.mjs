#!/usr/bin/env node
/**
 * Pinia store id regex check.
 *
 * The MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #2 rule states that every
 * Pinia store id declared inside ``frontend/src/modules/`` must match
 *
 *     ^module_[a-z][a-z0-9_]+$
 *
 * …so per-module stores never collide with the legacy ``defineStore('machine', ...)``
 * / ``defineStore('console', ...)`` ids that live in ``src/stores/``.
 *
 * This script is intentionally pure-Node (no Vite, no Vitest) so it
 * runs in CI before the bundle is even built. It exits non-zero on
 * the first violation, printing the offending file path and id so the
 * contributor can fix it without digging through logs.
 *
 * Usage:
 *   node scripts/check-store-ids.mjs
 *   node scripts/check-store-ids.mjs frontend/src/modules
 *
 * Exit codes:
 *   0 — every store id inside the scanned directory matches the regex.
 *   1 — at least one violation was found.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";

const DEFAULT_DIR = "frontend/src/modules";
const STORE_ID_RE = /^module_[a-z][a-z0-9_]+$/;
const DEFINE_STORE_RE = /defineStore\(\s*(['"])([^'"]+)\1/g;

function walk(dir) {
  const out = [];
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const name of entries) {
    const full = join(dir, name);
    let st;
    try {
      st = statSync(full);
    } catch {
      continue;
    }
    if (st.isDirectory()) {
      out.push(...walk(full));
    } else if (
      st.isFile() &&
      (extname(full) === ".js" || extname(full) === ".ts")
    ) {
      out.push(full);
    }
  }
  return out;
}

function check(rootDir) {
  const root = resolve(rootDir);
  const files = walk(root);
  const violations = [];
  for (const file of files) {
    const text = readFileSync(file, "utf-8");
    DEFINE_STORE_RE.lastIndex = 0;
    let match;
    while ((match = DEFINE_STORE_RE.exec(text))) {
      const id = match[2];
      if (!STORE_ID_RE.test(id)) {
        violations.push({
          file: relative(process.cwd(), file),
          id,
          line: text.slice(0, match.index).split(/\n/).length,
        });
      }
    }
  }
  return violations;
}

const target = process.argv[2] || DEFAULT_DIR;
const violations = check(target);

if (violations.length === 0) {
  // eslint-disable-next-line no-console
  console.log(`[lint:store-ids] OK (${target})`);
  process.exit(0);
}

for (const v of violations) {
  // eslint-disable-next-line no-console
  console.error(
    `[lint:store-ids] ${v.file}:${v.line}: Store id must match ${STORE_ID_RE} (got '${v.id}')`,
  );
}
process.exit(1);