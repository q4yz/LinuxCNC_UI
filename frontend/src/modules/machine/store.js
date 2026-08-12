// Machine module store — thin re-export of the cross-module
// runtime store at ``frontend/src/stores/machine.js``. The full
// Pinia store body (DRO computed values, hardware actions,
// program lifecycle, settings) lives in the runtime stores
// layer alongside ``stateFacade``, ``servoThread``, and
// ``baseThread`` so any cross-module consumer can import from a
// single place.
//
// Module-internal components (``DroPanel``, ``JogControls``)
// keep importing via the historical ``../store.js`` path so
// this module looks like every other module from the outside.
// The nullable-module contract this used to support has been
// dropped — the machine module is now a hard dependency
// (same as the temperature module).

export {
  useMachineStore,
  useMachineRefs,
} from "../../stores/machine.js";
