// Minimal loader hook. Resolves relative dynamic imports so the
// project's TypeScript source loads under the experimental
// strip-types loader (see --experimental-strip-types in the test
// script). Two transforms are applied to RELATIVE specifiers only:
//
//   * ``./foo.ts`` → resolve as ``./foo`` (TS5097 hot-fix; the
//     TypeScript compiler disallows importing a literal ``.ts``
//     without ``allowImportingTsExtensions``).
//   * ``./foo``    → fall back to ``./foo.ts`` if no other
//     extension resolves (this codebase writes most source as
//     ``.ts``; the ESM resolver, by design, will not guess the
//     extension).
//
// Absolute URLs / bare specifiers / non-relative paths pass
// through unchanged — the strip-types loader handles ``.ts`` files
// directly when the URL points at one.

export async function resolve(specifier, context, nextResolve) {
  const isRelative = specifier.startsWith('./') || specifier.startsWith('../');
  const hasExt = /\.[a-z0-9]+$/i.test(specifier);

  if (!isRelative) {
    // Absolute URLs and bare specifiers are handled by Node + the
    // strip-types loader directly; don't rewrite.
    return nextResolve(specifier, context);
  }

  if (hasExt) {
    // Relative + .ts: strip the extension so the resolver + strip
    // -types loader can complete the job.
    if (specifier.endsWith('.ts')) {
      return nextResolve(specifier.slice(0, -3), context);
    }
    return nextResolve(specifier, context);
  }

  // Relative + extensionless: try the default resolver first
  // (covers .js / .mjs / .cjs / package.json), then fall back to .ts.
  // Node's ESM resolver does not expand directory imports to an
  // ``index`` barrel (unlike bundlers), so also try
  // ``<specifier>/index.ts`` — src barrels like
  // ``entities/temperature`` rely on this under the test runner.
  try {
    return await nextResolve(specifier, context);
  } catch (err) {
    if (err && (err.code === 'ERR_MODULE_NOT_FOUND' || err.code === 'ERR_UNSUPPORTED_DIR_IMPORT')) {
      try {
        return await nextResolve(specifier + '.ts', context);
      } catch {
        return nextResolve(specifier + '/index.ts', context);
      }
    }
    throw err;
  }
}
