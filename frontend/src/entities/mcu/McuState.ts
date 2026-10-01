// MCU entity. Mirrors the ``McuStateResponse`` Pydantic shape emitted
// by the base-thread snapshot's static tier (``hardware.json``'s
// ``mcus[]``). Wholly static for a machine session.
//
// ``resettable`` is true for a Remora board that declared a
// ``reset_pin`` — the UI offers a reset button only when at least one
// MCU is resettable (``POST /api/v1/modules/mcu/reset``).

export interface McuStateParams {
  id?: string;
  connection?: string;
  resettable?: boolean;
}

export class McuState {
  private readonly _id: string;
  private readonly _connection: string;
  private readonly _resettable: boolean;

  constructor({ id = "", connection = "", resettable = false }: McuStateParams = {}) {
    this._id = typeof id === "string" ? id : "";
    this._connection = typeof connection === "string" ? connection : "";
    this._resettable = resettable === true;
  }

  get id(): string {
    return this._id;
  }

  get connection(): string {
    return this._connection;
  }

  get resettable(): boolean {
    return this._resettable;
  }
}
