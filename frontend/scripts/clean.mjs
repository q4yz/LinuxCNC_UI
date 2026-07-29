// Remove generated artefacts and caches.
//
// Used by ``npm run clean`` (and indirectly by the postinstall
// codegen fallback). Cross-platform replacement for ``rm -rf``,
// which doesn't exist on stock ``cmd.exe``.
//
// Targets mirror the directories produced by the build / codegen
// pipeline:
//   * ``generated``         — OpenAPI-generated client (gitignored).
//   * ``dist``              — Vite production build output.
//   * ``node_modules/.vite``— Vite optimized-deps cache. Removing it
//     forces Vite to re-scan globs / re-bundle pre-bundled deps
//     after a fresh checkout or after deleting the modules folder.
//
// Run with ``--dry`` to print the targets without deleting.

import { rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, '..');

const dryRun = process.argv.includes('--dry');

const targets = [
  { path: 'generated',          label: 'OpenAPI-generated client' },
  { path: 'dist',               label: 'Vite build output' },
  { path: 'node_modules/.vite', label: 'Vite optimized-deps cache' },
];

for (const t of targets) {
  const abs = path.join(projectRoot, t.path);
  if (dryRun) {
    console.log(`[clean] would remove ${t.path} (${t.label})`);
    continue;
  }
  try {
    await rm(abs, { recursive: true, force: true });
    console.log(`[clean] removed ${t.path} (${t.label})`);
  } catch (error) {
    // ``force: true`` already swallows ENOENT, so any error here
    // is worth surfacing.
    console.error(`[clean] failed to remove ${t.path}: ${error.message}`);
  }
}