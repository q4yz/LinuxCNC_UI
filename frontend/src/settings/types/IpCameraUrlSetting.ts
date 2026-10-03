import { defineAsyncComponent, type Component } from "vue";
import type { SettingOptions } from "../core/BaseSetting";
import { TextSetting } from "./TextSetting";

// Lazy: the editor .vue is only loaded when the Settings view renders it.
const SettingIpCameraUrl = defineAsyncComponent(() => import("../components/SettingIpCameraUrl.vue"));

/**
 * IP camera URL. Empty = no IP camera. Rejects ``user:pass@host``:
 * Chrome strips userinfo from cross-origin redirects, so such a URL
 * never authenticates — credentials belong in query parameters.
 */
export class IpCameraUrlSetting extends TextSetting {
  constructor(category: string, label: string, key: string, options: SettingOptions = {}) {
    super(category, label, key, "", { placeholder: "http://10.0.0.58/videostream.cgi?rate=0&user=...&pwd=..." }, options);
  }

  get type(): string {
    return "ip-camera-url";
  }

  get component(): Component {
    return SettingIpCameraUrl;
  }

  /** Why ``raw`` is not acceptable, or ``null`` when it is. */
  problem(raw: string): string | null {
    const url = raw.trim();
    if (url === "") return null;
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      return "Not a valid URL";
    }
    if (parsed.username || parsed.password) {
      return "URL contains embedded credentials (user:pass@host). Move them into query parameters (?user=...&pwd=...).";
    }
    return null;
  }

  validate(raw: unknown): string | undefined {
    const text = super.validate(raw);
    if (text === undefined) return undefined;
    return this.problem(text) === null ? text.trim() : undefined;
  }
}
