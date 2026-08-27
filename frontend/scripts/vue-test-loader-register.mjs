// Register a Node loader hook so `node --test` can dynamic-import the
// project's TypeScript source. Tests live in tests/test-*.mjs and
// import the entities / mappers / stores / facades directly by
// ../src/... path; without this hook Node's default ESM resolver
// refuses a literal `.ts` extension (TS5097) and the build also
// drops the `.ts` extension during runtime via the stripped-types
// loader (enabled by --experimental-strip-types on the test command).
//
// Pair with: scripts/vue-test-loader.mjs

import { register } from 'node:module'

register(new URL('./vue-test-loader.mjs', import.meta.url))
