// Read-only data loading for the Visual HAL Editor.
//
// Adapts the backend's real HAL world (`GET /api/v1/hal/layout` via
// [../../facades/halFacade.ts](../../facades/halFacade.ts)) into the
// shapes the canvas consumes:
//
//   * `HalPinResource` → `HalPin` (pins for the picker drawers)
//   * `HalSignalResource` → `SeedSignal` (existing signals, seeded
//     onto the canvas as pre-wired pin nodes)
//
// THIS MODULE IS READ-ONLY BY CONTRACT: the facade exposes a single
// `fetchLayout()` and nothing here (or anywhere in the editor) ever
// performs a write against the backend. In-session canvas edits are
// frontend state only; refreshing re-fetches and resets the canvas.

import HalVisualService from "../../facades/halFacade";
import type { HalPinResource, HalSignalResource } from "../../../generated/api";
import type { HalPin, PinType } from "./types";

const VALID_TYPES: ReadonlySet<Exclude<PinType, "auto">> = new Set([
  "bit",
  "float",
  "s32",
  "u32",
]);

/** A backend signal prepared for canvas seeding. */
export interface SeedSignal {
  name: string;
  source: HalPin | null;
  targets: HalPin[];
}

export interface HalLayoutData {
  pins: HalPin[];
  signals: SeedSignal[];
}

/** `HalPinResource.type` is a bare string — only real HAL tokens map to the editor. */
function pinType(token: string): Exclude<PinType, "auto"> | null {
  return VALID_TYPES.has(token as Exclude<PinType, "auto">)
    ? (token as Exclude<PinType, "auto">)
    : null;
}

function halPinFromResource(res: HalPinResource): HalPin | null {
  const type = pinType(res.type);
  if (!type) return null;
  const direction = res.direction === "out" ? "out" : "in";
  return {
    id: res.id,
    fullName: res.full_name,
    type,
    direction,
    componentName: res.component_name ?? undefined,
    description: res.description ?? undefined,
  };
}

function seedSignalFromResource(res: HalSignalResource): SeedSignal | null {
  if (!res.name) return null;
  const source = res.source ? halPinFromResource(res.source) : null;
  const targets: HalPin[] = [];
  for (const raw of res.targets ?? []) {
    const pin = halPinFromResource(raw);
    if (pin) targets.push(pin);
  }
  // A signal with neither end mapped has nothing to draw.
  if (!source && targets.length === 0) return null;
  return { name: res.name, source, targets };
}

/**
 * Fetch the real HAL world for the canvas. Returns `null` on any
 * transport failure (caller renders an error state with a Retry).
 */
export async function loadHalLayout(): Promise<HalLayoutData | null> {
  const layout = await HalVisualService.fetchLayout();
  if (!layout) return null;

  const pins: HalPin[] = [];
  for (const raw of [...(layout.in_pins ?? []), ...(layout.out_pins ?? [])]) {
    const pin = halPinFromResource(raw);
    if (pin) pins.push(pin);
  }

  const signals: SeedSignal[] = [];
  for (const raw of layout.signals ?? []) {
    const signal = seedSignalFromResource(raw);
    if (signal) signals.push(signal);
  }

  return { pins, signals };
}
