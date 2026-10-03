// Central UI settings facade. Wraps the generated ``SettingsService``
// (system service, ``/api/v1/settings``) — available while the machine
// backend is offline.
//
// Reads return plain data (the registry decides what to do with a
// failure); writes return a ``CommandResult`` like every other command,
// plus the backend's echoed value, which is the save confirmation.

import { SettingsService } from "../../generated/api/services/SettingsService";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";

export interface SettingRead {
  /** ``false`` when the key was never stored (404) — the default applies. */
  found: boolean;
  value: unknown;
}

export interface SettingWrite {
  result: CommandResult;
  /** The value the backend persisted (only on success). */
  value?: unknown;
}

/** Every stored setting, in one request. Throws on transport failure. */
async function listAll(): Promise<Record<string, unknown>> {
  const response = await SettingsService.listSettings();
  const values = response?.values;
  return values && typeof values === "object" ? (values as Record<string, unknown>) : {};
}

/** Fresh read of one key (critical settings). Throws on anything but 404. */
async function read(key: string): Promise<SettingRead> {
  try {
    const response = await SettingsService.readSetting(key);
    return { found: true, value: response.value };
  } catch (err: unknown) {
    if (errorStatus(err) === 404) return { found: false, value: undefined };
    throw err;
  }
}

async function write(key: string, value: unknown): Promise<SettingWrite> {
  const commandId = `setting:write:${key}`;
  try {
    const response = await SettingsService.writeSetting(key, { value });
    return { result: CommandResult.success({ commandId }), value: response.value };
  } catch (err: unknown) {
    return {
      result: CommandResult.failure(describeError(err), { commandId, statusCode: errorStatus(err) }),
    };
  }
}

async function reset(key: string): Promise<CommandResult> {
  const commandId = `setting:reset:${key}`;
  try {
    await SettingsService.resetSetting(key);
    return CommandResult.success({ commandId });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), { commandId, statusCode: errorStatus(err) });
  }
}

export const settingsFacade = Object.freeze({ listAll, read, write, reset });

export default settingsFacade;
