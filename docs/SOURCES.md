# Sources and compatibility

Author of the MG8/NYCH/TCTA family: Nicholas Hartman / American Milestone Inc.

Canonical schemas are included unchanged for offline conformance tests:

- `schemas/g8son.schema.json`: nhartman000/g8son, commit `ecb193d90189c8bfdb2d0e7cebb00432a1d0e260`, `schema/g8son.schema.json` (branch `000`).
- `schemas/qson.schema.json`: nhartman000/qson, commit `92e6e3e8f9f0fa4f501db21228116417d71df998`, `schema/qson.schema.json`.

Additional inspected baselines:

- MG8: `bd5fcee17a1b4173c39f92de46783c52cfb13f71`
- GST: `0d8aefbede38a6e9e8ec671ef9a135d491147ff2`
- MG8-engine: `c44ca2fac1849d973b65c9996a7d39ed586ea6e6`
- NYCH: `cee3610723ffe4877c424591711fed29717ab655`
- TCTA: `f2882c131e3e220d1cf1c9b7448625aabd51a85f`
- T.O.T.E-loops: `cad966090296130493ec6d84c3ed8de998524aa1`
- HDRP: `f5d26f47f8a8885dff63d84cb766d8ff152606b9`

This repository does not vendor or modify those engines. Its outcome/reason evaluator boundary is compatible in concept with NYCH AtomicRequirement, but NYCH's callback signature must be explicitly wrapped for this runtime's `(context, condition)` interface. A model's reported result is not substituted for host execution.

The local historical MGate Keeper files and ledger were inspected read-only. They are not republished as a new experiment here. The local demo uses its own clearly declared reference task and actual runtime execution.

The JSON ORK/BONIT loader profile is named explicitly; it is not an implementation of the full block-syntax ORK v0.3 reference profile. Future support requires a separate parser and compatibility decision. No existing artifact is silently renamed, normalized or migrated.
