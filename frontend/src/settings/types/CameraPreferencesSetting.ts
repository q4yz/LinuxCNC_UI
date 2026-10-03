import { defineAsyncComponent, type Component } from "vue";
import { BaseSetting, type SettingOptions } from "../core/BaseSetting";
import type { WirePreferenceMap } from "../../stores/cameraTypes";
import { deserializePreferences, serializePreferences } from "../../stores/cameraPreferenceCodec";

// Lazy: the editor .vue is only loaded when the Settings view renders it.
const SettingCameraPreferences = defineAsyncComponent(() => import("../components/SettingCameraPreferences.vue"));

/**
 * Per-camera display preferences (custom name, rotation, mirror, hide
 * from cycle), keyed by device id. Stored in the wire shape
 * (snake_case); the camera store works on a camelCase copy.
 */
export class CameraPreferencesSetting extends BaseSetting<WirePreferenceMap> {
  constructor(category: string, label: string, key: string, options: SettingOptions = {}) {
    super(category, label, key, {}, options);
  }

  get type(): string {
    return "camera-preferences";
  }

  get component(): Component {
    return SettingCameraPreferences;
  }

  /** Normalises every row (bad angles → 0, missing flags → false). */
  validate(raw: unknown): WirePreferenceMap | undefined {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
    return serializePreferences(deserializePreferences(raw));
  }
}
