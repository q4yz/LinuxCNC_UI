// I/O facade — fans, [output_pin] outputs and [input_pin] inputs
// (machine backend ``/api/v1/modules/io``, `.agent/component/io_pins.md`).
// Thin pass-through: callers catch and report errors via describeError.

import { ModulesIoService } from "../../generated/api/index";
import type { IoState } from "../../generated/api/index";

export type { IoState };

export const ioFacade = {
  state: (): Promise<IoState> => ModulesIoService.getIoState(),
  /** A fan in %, a PWM output in its scale units, a switched output 0 / 1. */
  set: (id: string, value: number): Promise<IoState> => ModulesIoService.setIoValue(id, { value }),
};

export default ioFacade;
