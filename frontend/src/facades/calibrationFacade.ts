// Calibration tab (machine backend, ``/api/v1/calibration``): the machine's
// calibrations with their last result and reminder; start one, set a
// reminder, clear saved values (calibration.ini). Thin pass-through:
// callers report errors.

import { CalibrationService } from "../../generated/api/index";
import type { CalibrationItem, CalibrationList } from "../../generated/api/index";
import { machineStateFacade } from "./machineStateFacade";

export type { CalibrationItem, CalibrationList };

export const calibrationFacade = {
  list: (): Promise<CalibrationList> => CalibrationService.getCalibrations(),
  start: (id: string, params: Record<string, number>): Promise<string> =>
    CalibrationService.startCalibration(id, { params }).then((r) => r.command),
  setReminder: (id: string, remindAt: string | null): Promise<CalibrationList> =>
    CalibrationService.setCalibrationReminder(id, { remind_at: remindAt }),
  clear: (id: string): Promise<CalibrationList> => CalibrationService.clearCalibration(id),
  // a guided calibration's measurements -> its result (saved and applied)
  submit: (id: string, values: Record<string, number>) => CalibrationService.submitCalibrationResult(id, { values }),
  // PROBE_CALIBRATE's TESTZ / ACCEPT / ABORT go through the console's MDI path
  command: (line: string) => machineStateFacade.sendMdi(line),
};

export default calibrationFacade;
