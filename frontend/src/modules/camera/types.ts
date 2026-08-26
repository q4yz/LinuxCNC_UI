// Shared types for the camera module. Centralised here so the
// store, the components, and the manifest pull from the same
// vocabulary. ``DeviceSource`` matches the values the backend
// returns on the ``/devices`` endpoint and the local preferences
// map. ``EditablePreferenceKey`` is the closed set of preference
// fields the Settings panel exposes; ``EDITABLE_KEYS`` in
// ``cameraStore.ts`` is typed against it so a future addition
// trips the type-checker rather than silently desynchronising
// from the operator surface.

export type DeviceSource = "usb" | "ip" | "unknown";

export interface CameraDevice {
  id: string;
  name: string;
  source: DeviceSource;
}

export interface CameraPreference {
  customName: string;
  flip: boolean;
  mirror: boolean;
  hidden: boolean;
}

export type EditablePreferenceKey = "customName" | "flip" | "mirror" | "hidden";

/** Map of camera id → per-device preference row. */
export type CameraPreferenceMap = Record<string, CameraPreference>;

/**
 * Wire-shape of a single preference row as the backend persists it
 * (``settings.json`` on disk uses snake_case). The store converts
 * between this and the camelCase ``CameraPreference`` shape at
 * the read / write boundary.
 */
export interface WirePreference {
  custom_name: string;
  flip: boolean;
  mirror: boolean;
  hidden: boolean;
}

export type WirePreferenceMap = Record<string, WirePreference>;

/** URL the viewer renders as ``<img src=...>`` while a stream is live. */
export interface StreamUrlContext {
  cameraId: string;
  /** Cache-buster timestamp the viewer appends to drop stale sockets. */
  timestamp: number;
}