// Print tuning (machine backend, ``/api/v1/print-tuning``): the live Z
// offset, flow, excluding objects and the slicer's progress of the
// loaded print. Thin pass-through: callers report errors.

import { PrintTuningService } from "../../generated/api/index";
import type { PrintTuningState } from "../../generated/api/index";

export type { PrintTuningState };

export const printTuningFacade = {
  get: (): Promise<PrintTuningState> => PrintTuningService.getPrintTuning(),
  adjustZ: (delta: number): Promise<PrintTuningState> => PrintTuningService.setPrintTuning({ z_adjust: delta }),
  setZ: (value: number): Promise<PrintTuningState> => PrintTuningService.setPrintTuning({ z_offset: value }),
  setFlow: (percent: number): Promise<PrintTuningState> => PrintTuningService.setPrintTuning({ flow: percent }),
  setPressureAdvance: (k: number): Promise<PrintTuningState> =>
    PrintTuningService.setPrintTuning({ pressure_advance: k }),
  exclude: (index: number, excluded: boolean): Promise<PrintTuningState> =>
    PrintTuningService.setObjectExcluded(index, { excluded }),
};

export default printTuningFacade;
