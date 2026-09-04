// Merges the two backend OpenAPI specs (machine :8000 + system :8001)
// into one document so `generate-api.mjs` can keep generating a
// single TypeScript client. Safe because the two services' routers
// were split along non-overlapping path prefixes (see
// backend/machine/main.py and backend/system/main.py) — a genuine
// collision here means a router got mounted in both apps, which is
// a real bug worth failing loudly on rather than silently letting
// one service's path shadow the other's.
//
// The one expected, harmless collision is each app's own bare "/"
// health check (`read_root` in both mains) — neither is part of the
// frontend's API contract, so it's excluded from the merge rather
// than tripping the collision guard.
const IGNORED_PATHS = new Set(['/']);

const COMPONENT_SECTIONS = [
  'schemas',
  'responses',
  'parameters',
  'examples',
  'requestBodies',
  'headers',
  'securitySchemes',
  'links',
  'callbacks',
];

export function mergeOpenApiSpecs(base, extra) {
  const merged = structuredClone(base);

  merged.paths = { ...(merged.paths ?? {}) };
  for (const path of IGNORED_PATHS) delete merged.paths[path];
  for (const [path, item] of Object.entries(extra.paths ?? {})) {
    if (IGNORED_PATHS.has(path)) continue;
    if (merged.paths[path]) {
      throw new Error(
        `OpenAPI merge conflict: path "${path}" is defined in both specs. ` +
          'Each router must be mounted in exactly one of the machine/system apps.',
      );
    }
    merged.paths[path] = item;
  }

  merged.components = { ...(merged.components ?? {}) };
  for (const section of COMPONENT_SECTIONS) {
    const baseSection = merged.components[section] ?? {};
    const extraSection = extra.components?.[section] ?? {};
    const combined = { ...baseSection };
    for (const [name, def] of Object.entries(extraSection)) {
      // Same schema name from both apps is fine as long as the
      // shape agrees (e.g. a shared DTO both routers reference) —
      // only flag it when the two definitions actually differ.
      if (combined[name] && JSON.stringify(combined[name]) !== JSON.stringify(def)) {
        throw new Error(
          `OpenAPI merge conflict: components.${section}.${name} differs between specs.`,
        );
      }
      combined[name] = def;
    }
    if (Object.keys(combined).length > 0) {
      merged.components[section] = combined;
    }
  }
  if (Object.keys(merged.components).length === 0) {
    delete merged.components;
  }

  const existingTagNames = new Set((merged.tags ?? []).map((t) => t.name));
  const mergedTags = [...(merged.tags ?? [])];
  for (const tag of extra.tags ?? []) {
    if (!existingTagNames.has(tag.name)) {
      mergedTags.push(tag);
      existingTagNames.add(tag.name);
    }
  }
  if (mergedTags.length > 0) {
    merged.tags = mergedTags;
  }

  return merged;
}
