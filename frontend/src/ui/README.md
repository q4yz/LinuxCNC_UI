# `frontend/src/ui/` — shared UI primitives

Four Vue 3 components that consolidate the visual language shared by every dashboard panel, modal, and toolbar in the project. **Every new component MUST reach for these before inventing its own.** The whole point of the library is to keep the operator-facing UI consistent: a future palette change touches one file, not a dozen.

## Contents

| Component | Role | When to use |
|---|---|---|
| [`Button.vue`](#button) | Primary action primitive | Every `<button>` or `<a class="...">` that triggers an action |
| [`Icon.vue`](#icon) | Inline SVG icon primitive | Every icon next to a label or as a toolbar glyph |
| [`Drawer.vue`](#drawer) | Slide-in panel primitive | Right-side alarm history, future settings detail |
| [`Confirm.vue`](#confirm) | Single-modal confirmation | Inline confirmations gated by app state |

All four are imported from a single barrel — `import { Button, Icon, Drawer, Confirm } from "@/ui"` (use the relative path until the project's `@` alias lands in `vite.config.js`).

---

## Button

`<Button>` replaces the four ad-hoc class soups that previously appeared across the dashboard:

| Old pattern | New pattern |
|---|---|
| `<button class="rounded bg-blue-600 hover:bg-blue-500 text-white font-semibold px-4 py-2">Save</button>` | `<Button variant="primary">Save</Button>` |
| `<button class="rounded bg-red-600 hover:bg-red-500 text-white font-semibold px-3 py-1.5 text-sm">Delete</button>` | `<Button variant="danger" size="sm">Delete</Button>` |

### Props

| Prop | Type | Default | Notes |
|---|---|---|---|
| `variant` | `"primary"` \| `"success"` \| `"danger"` \| `"secondary"` \| `"ghost"` | `"primary"` | Pick by operator intent: success for "go" actions, danger for destructive, secondary for cancel, ghost for in-row icons. |
| `size` | `"sm"` \| `"md"` \| `"lg"` | `"md"` | `lg` is reserved for dashboard CTAs (`ActivePrintWidget`'s Start button). |
| `loading` | Boolean | `false` | Auto-implies `disabled`; renders a spinner. |
| `disabled` | Boolean | `false` | Forwarded to the underlying button. |
| `type` | `"button"` \| `"submit"` \| `"reset"` | `"button"` | Defaults to `button` so a stray use in a form does not submit. |

### Slots

- `icon` — rendered before the default slot. Use for an `<Icon>` glyph on the left of the label.
- default — the visible label.

### Examples

```vue
<Button variant="primary" @click="save">Save changes</Button>

<Button variant="danger" :loading="isDeleting" @click="confirmDelete">
  Delete profile
</Button>

<Button variant="secondary" size="sm">
  <template #icon><Icon name="refresh" /></template>
  Refresh
</Button>
```

---

## Icon

`<Icon name="...">` is the canonical inline SVG. The set is the small one the operator actually sees today; adding a new one is one entry in the `ICONS` table.

### Props

| Prop | Type | Default | Notes |
|---|---|---|---|
| `name` | String (required) | — | Must match an entry in the `ICONS` table. Unknown names render an empty `<svg>` placeholder so layouts do not shift. |
| `size` | Tailwind class string | `"h-4 w-4"` | Matches the inline icons in `AppSidebar.vue:28-30` (16×16 px). |
| `label` | Boolean | `false` | When `true`, exposes `aria-label` for screen readers. Default `false` uses `aria-hidden="true"` since most icons sit next to a text label. |

### Available icons

`close`, `edit`, `delete`, `save`, `refresh`, `plus`, `alert`, `info`, `check`, `chevronDown`, `chevronLeft`, `warning`, `plusCircle`.

### Examples

```vue
<Icon name="refresh" />
<Icon name="delete" class="text-red-400" />
<Icon name="alert" size="h-5 w-5" label />  <!-- screen-reader accessible -->
```

---

## Drawer

`<Drawer>` is the right-anchored slide-over panel. Used today by future alarm history; today it powers the sidebar collapse pattern (which will migrate in a follow-up).

### Props

| Prop | Type | Default | Notes |
|---|---|---|---|
| `open` | Boolean (v-model) | `false` | Two-way bound. Setting `false` from outside triggers the close transition and emits `close`. |
| `side` | `"right"` \| `"left"` | `"right"` | Right is the operator-side anchor; left is reserved for future asymmetry. Top/bottom are not currently supported. |
| `width` | Tailwind class string | `"w-96"` | Consumer picks the footprint. |
| `closeOnBackdrop` | Boolean | `true` | Disable for destructive flows the operator must explicitly confirm. |
| `closeOnEsc` | Boolean | `true` | Disable for the same reason. |

### Events

- `update:open` — two-way binding.
- `close` — emitted whenever the drawer closes (backdrop / Esc / parent-driven). The drawer does not differentiate sources.

### Slots

- `header` — chrome (title, close button). Recommended; the drawer reserves no chrome of its own.
- default — body. Scrolls independently.

### Example

```vue
<Drawer v-model:open="showHistory" width="w-[28rem]">
  <template #header>
    <div class="flex items-center justify-between px-4 py-3 border-b border-gray-700">
      <h2 class="font-semibold">Alarm history</h2>
      <button @click="showHistory = false">
        <Icon name="close" />
      </button>
    </div>
  </template>
  <ul>
    <li v-for="entry in history" :key="entry.id">{{ entry.text }}</li>
  </ul>
</Drawer>
```

---

## Confirm

`<Confirm>` is the inline single-modal confirmation. Two flavours live in the codebase today; this is the second one.

| Flavour | File | When to use |
|---|---|---|
| **Queue-based** — `useConfirm()` in `core/confirm.js` → `ModalConfirmHost.vue` → `ModalConfirm.vue` | One click handler can resolve multiple confirms correctly |
| **Inline** — `<Confirm v-model:open="…"/>` directly in a host | Confirmations gated by app state (`showDelete = …`) or driven by a watcher |

Both flavours share the same Tailwind palette so operators see a single visual language.

### Props

| Prop | Type | Default | Notes |
|---|---|---|---|
| `open` | Boolean (v-model) | `false` | Two-way bound. |
| `title` | String | `"Confirm"` | Header text. |
| `question` | String | `"Are you sure?"` | Body text. |
| `description` | String | `""` | Optional secondary line below the question. |
| `confirmButtonText` | String | `"Confirm"` | Operator-facing button label — match the action verb. |
| `rejectButtonText` | String | `"Cancel"` | Cancel-button label. |
| `confirmButtonStyle` | `"primary"` \| `"success"` \| `"danger"` | `"primary"` | `danger` for destructive actions, `success` for "go" actions. |
| `rejectButtonStyle` | `"primary"` \| `"secondary"` | `"secondary"` | `secondary` (outlined) is the muted cancel style. |
| `closeOnBackdrop` | Boolean | `true` | Disable for destructive flows. |
| `closeOnEsc` | Boolean | `true` | Same reason. |
| `showDismissCrossButton` | Boolean | `true` | The `×` in the header. |

### Events

- `update:open` — two-way binding.
- `confirm` — operator accepted. Treat this as the destructive path.
- `cancel` — operator dismissed (backdrop / Esc / `×` / cancel button). Treat this as the safe path.

### Keyboard

- `Escape` → `cancel`.
- `Enter` → `confirm`. (`Shift+Enter` is intentionally not bound so a multi-line input does not accidentally trigger confirm on newline.)

### Examples

```vue
<Confirm
  v-model:open="showDelete"
  title="Delete profile?"
  question="This will remove the .macro file from disk."
  description="The change is permanent."
  confirm-button-text="Delete"
  confirm-button-style="danger"
  @confirm="doDelete"
  @cancel="cancelDelete"
/>
```

---

## Adding a new primitive

1. Create `frontend/src/ui/<Name>.vue` — keep it single-purpose, dependency-light, and use the existing primitives (e.g. `Confirm.vue` uses `Button` + `Icon`).
2. Add the export to `frontend/src/ui/index.js`.
3. Add a regression test in `frontend/tests/test-ui-primitives.mjs`.
4. Add a section to this README documenting the contract.

Primitive additions are gated on appearing in 3+ unrelated call sites; one-off UI stays in the consuming component.

---

## QA matrix (manual)

The tests above pin the public contract; the following list of manual QA steps documents the runtime behaviour. Run before merging UI changes.

### Button
- [ ] Disabled state shows muted opacity (`opacity-50`) and `cursor-not-allowed`.
- [ ] Loading state shows a spinner and is non-clickable.
- [ ] Click fires once on rapid double-click (no internal debounce needed).
- [ ] `type="submit"` inside a `<form>` submits the form.

### Icon
- [ ] Unknown `name` renders an empty `<svg>` placeholder of the requested size (no shift).
- [ ] `aria-hidden="true"` by default; `aria-label="X"` when `label=true`.

### Drawer
- [ ] `Escape` and backdrop click both close.
- [ ] Body scrolls inside the drawer; the header stays anchored.
- [ ] Transition is visible on open and on close.
- [ ] Multi-instance: two drawers on the same page don't fight over the `keydown` listener.

### Confirm
- [ ] `Enter` confirms, `Escape` cancels.
- [ ] Backdrop click + `×` button both cancel (not confirm).
- [ ] Body scroll locks while the modal is open.
- [ ] `cancelButtonStyle` and `confirmButtonStyle` render through `Button.vue` (no separate styling branch).
- [ ] Multi-instance: opening a second confirm while the first is open works correctly.
