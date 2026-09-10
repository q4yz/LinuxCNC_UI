## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for a block matching the
syntax below. Not a component — it emits no HAL and no INI. It is a
global compiler directive that changes how the pin router's own
safety guard behaves.

**Component ID Format:** `duplicate_pin_override` (bare, singleton —
at most one per machine).

**Expected Syntax:**
```cfg
[duplicate_pin_override]
    pins: string // Comma-separated list of pin references
```

Example — the reference PrintNC-WEBGUI machine's shared X/Z home
switch, if it were declared as two independent endstop entities rather
than one shared one (see § 4 below for why that distinction matters):

```cfg
[duplicate_pin_override]
    pins: par0:13, par0:15
```

Each entry uses the same `[modifiers][mcu:]pin` grammar as any other
pin field (README § 1); modifiers are stripped before storing, since a
physical-pin collision is a property of the raw pin, not of how one
particular caller happens to invert it. A bare pin (no `mcu:` prefix)
defaults to the MCU named `"mcu"`, matching every other pin field's
default.

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "duplicate_pin_overrides": ["par0:13", "par0:15"]
}
```

A root-level list, normalised to `"<mcu_id>:<pin_id>"` strings —
sibling to `axes`/`joints`/`mcus`, not nested under any one entity,
since it is a cross-cutting exception rather than something one
component owns.

## 3. COMPILATION (INI & HAL)

Nothing. This directive never appears in `machine.ini`, `machine.hal`,
or any sidecar — it only changes which diagnostics the compiler emits
and how the pin router resolves a collision it would otherwise reject.

## 4. COMPILER RULES (Pin Router Guard)

**The problem this solves.** `E_PIN_CONFLICT` (README § 3) rejects two
different pin claims on the same `(mcu_id, pin_id)` — the right
default, since it is usually a typo. But a HAL pin belongs to exactly
one signal, and there is exactly one *structurally* safe way to share
one physical input across two consumers: give both consumers the
*same* signal name up front, so they were never two claims to begin
with. `stepper.md` already does this for the common case — two axes
referencing the *same* `endstops[]` entity collapse onto one signal
naturally, no override needed (see `README.md` § 3's `E_PIN_CONFLICT`
note and the golden test against PrintNC-WEBGUI's real "home-xz"
switch). **`[duplicate_pin_override]` exists for the case that trick
doesn't cover**: two genuinely independent entities — declared
separately, with different ids, by unrelated components — that the
operator has verified share one physical input pin on purpose.

**Validator.** For any pin claim whose `(mcu_id, pin_id)` appears in
`duplicate_pin_overrides`, skip `E_PIN_CONFLICT` entirely — it is
never recorded as a claim, so it can't conflict with itself or
anything else either. This is the *only* rule the override affects;
every other check (motion class, referential integrity, ranges, ...)
still runs normally against these pins.

**Router / assembler.** Skipping the diagnostic is not enough on its
own — two independently-emitted signal names still cannot both bind to
one physical pin without a HAL load error. The assembler is what makes
the result actually valid: for every override-listed pin claimed under
more than one signal name, it picks the first-seen signal as canonical
and rewrites every other fragment's `net` lines (and pin requests)
that named a "losing" signal to use the canonical one instead — so
they collapse onto one physical route exactly like a true shared
endstop would, with one writer and every original reader intact.

```hal
# Physical pin bound once, under whichever signal name was seen first.
net endstop_x-sw <= parport.0.pin-13-in-not

# Every consumer that asked for a *different* signal name on this
# pin now reads the same one — rewritten by the assembler, not
# re-emitted by either component.
net endstop_x-sw => joint.0.home-sw-in
net endstop_x-sw => joint.3.home-sw-in
```

**Not a global bypass.** Only pins named in `pins:` are exempt — an
operator typo that collides two *unrelated* pins is still
`E_PIN_CONFLICT`. Listing a pin here is a deliberate, auditable "yes,
this one's on purpose," not a way to silence the guard machine-wide.
