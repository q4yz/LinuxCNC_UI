// Fetch the FastAPI OpenAPI schema from the running backend and regenerate the
// strongly-typed client under src/services/api.
//
// Why a wrapper instead of pointing openapi-typescript-codegen directly at the
// URL: the generator's underlying json-schema-ref-parser chokes when handed a
// remote URL because it tries to interpret the URL itself as a $ref pointer.
// Downloading the spec to a local file first sidesteps that limitation while
// still respecting the workflow described in issue #19.
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

const openApiUrl = process.env.OPENAPI_URL ?? 'http://127.0.0.1:8000/openapi.json';
const outputDir = path.join(projectRoot, 'src', 'services', 'api');
const cacheDir = path.join(projectRoot, '.openapi-cache');
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
    const bin = path.join(projectRoot, 'node_modules', '.bin', 'openapi');
    const child = spawn(bin, generatorArgs, { stdio: 'inherit' });
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
