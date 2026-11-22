// Camera facade (machine backend ``/api/v1/modules/camera``): the device
// list, the stream supervisor's status and a stream diagnosis. Thin
// pass-through: the camera store interprets the payloads.

import { ModulesCameraService } from "../../generated/api/services/ModulesCameraService";

export const cameraFacade = {
  /** ``{ devices: [...] }`` — the cameras the backend can open. */
  listDevices: (): Promise<Record<string, unknown>> => ModulesCameraService.listCameraDevices(),
  /** ``{ message }`` — empty while the stream is healthy. */
  status: (): Promise<Record<string, unknown>> => ModulesCameraService.getCameraStatus(),
  /** ``{ ok, message }`` for ``deviceId`` (none: the default device). */
  diagnose: (deviceId?: string): Promise<Record<string, unknown>> => ModulesCameraService.diagnoseCameraStream(deviceId),
};

export default cameraFacade;
