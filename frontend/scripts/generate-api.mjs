// Fetch the FastAPI OpenAPI schema from the running backend and regenerate the
// strongly-typed client under `generated/api/` (gitignored — never committed).
//
// Why a wrapper instead of pointing openapi-typescript-codegen directly at the
// URL: the generator's underlying json-schema-ref-parser chokes when handed a
// remote URL because it tries to interpret the URL itself as a $ref pointer.
// Downloading the spec to a local file first sidesteps that limitation while
// still respecting the workflow described in issue #19.
//
// Why `generated/api/` (outside `src/`): a single, recognisable home for every
// auto-generated artifact in the project — nothing hand-written lives there.
// It is matched by `frontend/generated/` in the root `.gitignore`, so a
// successful regen never produces a noisy diff.
//
// Usage:
//   npm run generate-api                       # uses http://127.0.0.1:8000
//   OPENAPI_URL=http://host:8000 npm run generate-api

import { spawn } from 'node:child_process';
import { mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, '..');

// ``installMode`` is enabled when invoked via the ``postinstall`` npm
// hook — typically a fresh checkout, no backend running. In that
// mode a missing backend logs a warning instead of failing the
// install; the user can run ``npm run generate-api`` once the
// backend is reachable.
//
// Detection narrows ``npm_lifecycle_event`` to the literal
// ``"postinstall"`` value. The previous check
// (``Boolean(process.env.npm_lifecycle_event)``) was a no-op
// distinction — every ``npm run X`` invocation sets that variable,
// so ``npm run generate-api`` silently entered install mode and
// ``process.exit(0)``'d on fetch failure. Restricting to
// ``"postinstall"`` makes ``npm run generate-api`` exit non-zero
// when the backend is unreachable, surfacing the error to the
// bash script's curl poll instead of swallowing it.
const installMode =
  process.argv.includes('--install') ||
  process.env.npm_lifecycle_event === 'postinstall';

const openApiUrl = process.env.OPENAPI_URL ?? 'http://127.0.0.1:8000/openapi.json';
const generatedDir = path.join(projectRoot, 'generated');
const outputDir = path.join(generatedDir, 'api');
const cacheDir = path.join(generatedDir, '.openapi-cache');
const specPath = path.join(cacheDir, 'openapi.json');

const generatorArgs = [
  '--input', specPath,
  '--output', outputDir,
  '--client', 'fetch',
  '--useUnionTypes',
  '--exportCore', 'true',
  '--exportServices', 'true',
  '--exportModels', 'true',
  '--exportSchemas', 'false',
];

async function downloadSpec() {
  console.log(`[generate-api] Fetching OpenAPI schema from ${openApiUrl}`);
  const response = await fetch(openApiUrl);
  if (!response.ok) {
    throw new Error(`Failed to download OpenAPI schema: HTTP ${response.status}`);
  }
  const text = await response.text();
  // Sanity check: must be parseable JSON, otherwise the generator will fail.
  JSON.parse(text);
  await mkdir(cacheDir, { recursive: true });
  await writeFile(specPath, text, 'utf-8');
  console.log(`[generate-api] Wrote ${specPath} (${text.length} bytes)`);
}

function runGenerator() {
  return new Promise((resolve, reject) => {
    const isWin = process.platform === 'win32';
    // Windows ships the CLI as ``node_modules/.bin/openapi.cmd``.
    // Node's ``spawn`` does not auto-resolve the ``.cmd`` extension
    // unless ``shell: true`` is set; with ``shell: true`` the OS
    // shell (cmd.exe on Windows, /bin/sh elsewhere) parses the
    // command and handles extensions + spaces correctly. We pass
    // the binary + args as a single shell-quoted string so paths
    // containing spaces (``C:\Users\...``) survive intact.
    const binExt = isWin ? '.cmd' : '';
    const bin = path.join(projectRoot, 'node_modules', '.bin', `openapi${binExt}`);
    const quoted = generatorArgs
      .map((a) => (/[\s"]/.test(a) ? `"${a.replace(/"/g, '\\"')}"` : a))
      .join(' ');
    const child = spawn(`"${bin}" ${quoted}`, {
      stdio: 'inherit',
      shell: true,
    });
    child.on('error', reject);
    child.on('exit', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`openapi-typescript-codegen exited with code ${code}`));
    });
  });
}

async function main() {
  try {
    await downloadSpec();
  } catch (error) {
    if (installMode) {
      console.warn(`[generate-api] Skipped (install mode): ${error.message}`);
      console.warn('[generate-api] Backend is not reachable — generated client was not regenerated.');
      console.warn('[generate-api] Once the FastAPI backend is running on', openApiUrl, 'run:');
      console.warn('    npm run generate-api');
      process.exit(0);
    }
    console.error(`[generate-api] ${error.message}`);
    console.error('[generate-api] Is the FastAPI backend running on the expected port?');
    process.exit(1);
  }

  console.log('[generate-api] Regenerating client under', path.relative(projectRoot, outputDir));
  await rm(outputDir, { recursive: true, force: true });
  await runGenerator();
  console.log('[generate-api] Done.');
}

main().catch((error) => {
  console.error('[generate-api] Failed:', error);
  process.exit(1);
});
