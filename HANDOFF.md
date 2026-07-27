### Resolution Summary
Added a strictly typed Klipper-style configuration pipeline that validates every supported LinuxCNC-facing section, rejects undefined keywords with section/key details, builds linked dataclass component objects, and feeds the validated graph into the existing Klipper-to-LinuxCNC compiler.

### Files Modified
- `backend/modules/machineconfig/schema.py` (new): Defines supported section patterns, exact allowed-key sets, ignored printer keys, and the explicit MCU bypass contract.
- `backend/modules/machineconfig/models.py` (new): Defines dataclasses for printer, steppers, secondary endstops, extruder, heated bed, spindle, and the compiler-ready machine graph.
- `backend/modules/machineconfig/parser.py` (new): Implements case-preserving INI parsing, strict keyword/section and typed-value validation, actionable error classes, ignored-setting remarks, and deferred endstop-to-stepper linking.
- `backend/modules/machineconfig/compilers/klipper_linuxcnc.py`: Replaces best-effort printer parsing with the strict parser and validates the source before staging any artifact.
- `backend/tests/test_machineconfig_parser.py` (new): Demonstrates invalid-key rejection and verifies linked endstop objects, MCU bypass behavior, typed values, and missing-stepper errors.
- `HANDOFF.md`: Records the issue #51 implementation and verification results.

### Architectural Decisions
- The parser lives at the `machineconfig` module boundary, separate from schemas, dataclass models, and artifact compilation. This keeps validation reusable while allowing the existing compiler to consume the graph.
- Keyword names are case-preserved so the declared Klipper PID keys (`pid_Kp`, `pid_Ki`, `pid_Kd`) remain exact and misspellings cannot be silently normalized.
- MCU sections accept and bypass their transport-specific contents because the issue explicitly marks `[mcu]` and `[mcu <name>]` as ignored for LinuxCNC; all modelled sections enforce exact allowlists.
- Secondary endstops are resolved after all sections are parsed, allowing them to appear before their target stepper while still producing bidirectional object links (`EndstopSwitch.stepper` and `Stepper.endstops`).
- Listed component properties are optional unless graph integrity requires them; the `stepper` key on a secondary endstop is mandatory because the object cannot otherwise be linked. Present numeric and enumerated values are validated strictly.

### Testing Verification
- [x] `python -m pytest backend/tests/` — 150 passed, including the new invalid-key and object-graph tests.
- [x] `python -m compileall -q backend` — completed without errors.
- [x] `npm --prefix frontend run build` — production build completed successfully (existing chunk-size/dynamic-import warnings only).
- [x] `python -m pip install -r backend/requirements.txt` — all backend requirements satisfied in the provided `.venv`.
- [ ] `python3 -m venv .venv` could not recreate the runner-provided environment because the host lacks `ensurepip`/`python3.12-venv`; the existing `.venv` remained usable for all Python checks.
- [ ] The prescribed install-only commands could not complete: root `npm ci` has no root `package-lock.json`, and `npm --prefix frontend ci` reports the existing frontend lock file is missing `@emnapi/runtime@1.11.3`. The already-installed frontend dependencies successfully produced the production build.
