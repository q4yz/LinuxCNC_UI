// Base class for every UI setting.
//
//   export const estopDisablesPower = new CheckboxSetting(
//     "Machine", "Turn power off on E-Stop", "machine.estop_disables_power", false);
//
//   if (estopDisablesPower.value) { ... }      // anywhere, reactive
//
// A setting is defined once in ``settings/definitions/*`` (eagerly
// imported), registers itself, shows up in the generated Settings view
// under its category, and is persisted in the system service's single
// settings store under its namespaced key.
//
// Value semantics:
//   * normal: ``value`` = stored value, or the default until/unless one
//     is stored (UI-only settings — a default is fine).
//   * ``critical``: something outside this browser depends on it (the
//     camera supervisor reads it). Never served from the session cache:
//     ``value`` is ``null`` until a fresh ``load()`` has read it.
//
// Subclasses must not declare class fields: field initializers run after
// ``super()``, i.e. after registration. Type config (options, min/max)
// goes through ``options.config`` so it is part of the signature used to
// detect conflicting definitions.

import { markRaw, ref, shallowRef, type Component } from "vue";
import { CommandResult } from "../../entities/common/CommandResult";
import { reportCommandFailure } from "../../core/error-format";
import { settingsFacade } from "../../facades/settingsFacade";
import { describeError } from "../../core/error-format";
import { settingsRegistry } from "./settingsRegistry";
import { settingsLog } from "./settingsLog";

export interface SettingOptions {
  /** Read fresh, never from cache; no default shown until loaded. */
  critical?: boolean;
  /** Longer help text shown under the label. */
  description?: string;
  /** Sort order inside the category (lower first, then by label). */
  order?: number;
  /** Type-specific configuration (select options, number bounds, …). */
  config?: Record<string, unknown>;
}

const fmt = (value: unknown) => {
  if (value === undefined) return "unset";
  const text = JSON.stringify(value);
  return text && text.length > 80 ? `${text.slice(0, 77)}...` : String(text);
};

export abstract class BaseSetting<T> {
  readonly category: string;
  readonly label: string;
  readonly key: string;
  readonly defaultValue: T;
  readonly critical: boolean;
  readonly description: string;
  readonly order: number;
  protected readonly config: Readonly<Record<string, unknown>>;

  private readonly _stored = shallowRef<T | undefined>(undefined);
  private readonly _loaded = ref(false);

  constructor(category: string, label: string, key: string, defaultValue: T, options: SettingOptions = {}) {
    this.category = category;
    this.label = label;
    this.key = key;
    this.defaultValue = defaultValue;
    this.critical = options.critical === true;
    this.description = options.description ?? "";
    this.order = options.order ?? 0;
    this.config = Object.freeze({ ...(options.config ?? {}) });
    // Keep the instance out of Vue's deep reactivity: a reactive proxy
    // would unwrap ``_stored`` and break ``.value``. The refs inside
    // already make ``value`` reactive.
    markRaw(this);
    settingsRegistry.register(this);
  }

  /** Short type tag, part of the signature (``checkbox``, ``select``…). */
  abstract get type(): string;

  /** The editor component the Settings view renders (gets ``:setting``). */
  abstract get component(): Component;

  /** Coerce/check a raw stored value; ``undefined`` = invalid. */
  abstract validate(raw: unknown): T | undefined;

  /** Current value — see the class header for the critical rule. */
  get value(): T | null {
    const stored = this._stored.value;
    if (this.critical) return this._loaded.value ? (stored ?? this.defaultValue) : null;
    return stored ?? this.defaultValue;
  }

  /** ``true`` once the backend value (or "unset") is known. */
  get isLoaded(): boolean {
    return this._loaded.value;
  }

  /** ``true`` when a value is stored (i.e. not the default). */
  get isStored(): boolean {
    return this._stored.value !== undefined;
  }

  /** Identity for duplicate-definition detection. */
  signature(): string {
    return JSON.stringify([
      this.type,
      this.category,
      this.label,
      this.defaultValue,
      this.critical,
      this.description,
      this.order,
      this.config,
    ]);
  }

  /** Apply a raw backend value (``undefined`` = unset). Used by the registry and ``load``. */
  hydrate(raw: unknown): void {
    if (raw === undefined) {
      this._stored.value = undefined;
    } else {
      const valid = this.validate(raw);
      if (valid === undefined) {
        settingsLog("warning", `Setting ${this.key}: stored value ${fmt(raw)} is invalid — using default ${fmt(this.defaultValue)}`);
      }
      this._stored.value = valid;
    }
    this._loaded.value = true;
  }

  /** Fresh read of this one key (critical settings, or an explicit refresh). */
  async load(): Promise<boolean> {
    try {
      const { found, value } = await settingsFacade.read(this.key);
      this.hydrate(found ? value : undefined);
      return true;
    } catch (err: unknown) {
      settingsLog("warning", `Setting ${this.key}: could not load (${describeError(err)})`);
      return false;
    }
  }

  /**
   * Persist ``next``. The backend echoes what it stored; that echo
   * becomes the value (it is what the editors' sync contract waits
   * for). A failure leaves the value untouched and is reported.
   */
  async save(next: T): Promise<CommandResult> {
    const valid = this.validate(next);
    if (valid === undefined) {
      const result = CommandResult.failure(`Invalid value ${fmt(next)} for setting ${this.key}`, {
        commandId: `setting:write:${this.key}`,
      });
      reportCommandFailure(`save setting ${this.label}`, result);
      return result;
    }
    const { result, value } = await settingsFacade.write(this.key, valid);
    if (result.failed) {
      reportCommandFailure(`save setting ${this.label}`, result);
      return result;
    }
    this.hydrate(value);
    settingsLog("debug", `Setting ${this.key}: saved ${fmt(value)}`);
    return result;
  }

  /** Remove the stored value — the default applies again. */
  async reset(): Promise<CommandResult> {
    const result = await settingsFacade.reset(this.key);
    if (result.failed) {
      reportCommandFailure(`reset setting ${this.label}`, result);
      return result;
    }
    this.hydrate(undefined);
    settingsLog("debug", `Setting ${this.key}: reset to default ${fmt(this.defaultValue)}`);
    return result;
  }
}
