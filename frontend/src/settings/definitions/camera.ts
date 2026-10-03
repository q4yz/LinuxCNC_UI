// Camera settings. The URL and default device are **critical**: the
// machine backend's camera supervisor reads them from the settings file
// itself, so the UI never shows a cached copy of them.
import { CameraPreferencesSetting } from "../types/CameraPreferencesSetting";
import { IpCameraUrlSetting } from "../types/IpCameraUrlSetting";
import { TextSetting } from "../types/TextSetting";

export const ipCameraUrl = new IpCameraUrlSetting("Camera", "IP camera URL", "camera.ip_camera_url", {
  critical: true,
  order: 0,
  description:
    "HTTP or RTSP camera added to the camera list. Put credentials in query parameters (&user=...&pwd=...); embedded user:pass@host credentials are stripped by the browser.",
});

export const defaultCameraDevice = new TextSetting(
  "Camera",
  "Default camera device",
  "camera.default_device_id",
  "",
  { placeholder: "e.g. /dev/video0 — empty = first detected" },
  { critical: true, order: 1, description: "Device the camera stream uses when none is selected." },
);

export const cameraPreferences = new CameraPreferencesSetting("Camera", "Camera display preferences", "camera.preferences", {
  order: 2,
  description: "Name, orientation and hide flag per camera — shared by every browser.",
});
