# Implemented profile and remaining boundaries

## Implemented v0.1

The normative target is `AGENT_RUNTIME_CONTRACT.md` (proposed contract v0.2). This release implements its core admission/commit path through a narrower named execution profile.

| Contract area | Executable implementation |
|---|---|
| Conditions and logic | `gates.py`: authored requirement IDs/text, explicit evaluator bindings, mechanical predicates, AND/OR/NAND/NOR, unresolved propagation |
| Candidate vs committed state | `runtime.py`: detached JSON snapshots, scoped proposals, state version / epoch checks |
| Evidence | Host-only receipts bound to proposal/candidate; provenance, expiry and receipt digest checked again at admission |
| Admission | Required gate coverage, all required gates passing, explicit terminal commit route, optional prior admissibility callback |
| Permits | SQLite-backed issuance, revocation, expiry checks and atomic single-use consumption |
| Local state commit | Candidate state, permit consumption, proposal status, controller version and QSON event in one SQLite transaction |
| Effects | Separate pre-effect gates, allowlisted host adapter, durable dispatch record, bounded worker, post-effect reevaluation and explicit reconciliation |
| Bounded loops | Per-step run budget shared across replacement proposals; repair only on declared repeat routes; unresolved exhaustion |
| Durability/evidence | WAL/FULL SQLite, append-only event triggers, per-run sequence/identity, hash-chain validation, canonical QSON export |
| Resources | Confined relative resource loading, strict JSON/profile validation, complete sequential gate coverage and byte-digest source snapshots |
| Example | Offline requirement-driven FAIL -> revised candidate -> PASS -> committed GST and QSON |

## Deliberately not claimed

- A secure sandbox for arbitrary Python agents or host-registered evaluators. Deployment must enforce OS/process capabilities.
- A general compiler that translates arbitrary prose into predicates or loops. Historical control/context instructions require reviewed explicit adapters.
- A universal scientific-truth, simplicity or human-review service. A domain owner registers the actual evaluator/rubric and evidence policy.
- Reproducible token generation from every provider, proof that a semantic assessment is true, or byte-identical runtime timestamps/identifiers.
- A built-in universal TCTA Gamma/Psi implementation, global trajectory enumeration, automatic HDRP profile selection, or full NYCH pipeline. A required admissibility evaluator is an integration hook, not a claim those algorithms ran.
- Full ORK v0.3 block grammar, arbitrary BONIT language, nested/parallel package graphs, `.mg8pk` archives, or implicit multi-GST merging.
- Atomic transactions across arbitrary external APIs and local SQLite; universal exactly-once external effects; rollback of effects already observed.
- Direct commitment of mutable external files. The committed state is JSON in the runtime database. A real workspace adapter must stage and bind exact artifact bytes and implement independent postcondition verification.
- A background service, distributed recovery coordinator, provider credential manager, model account automation, or automatic live-provider rerun of historical evidence.

## Supported resource representation

MG8 manifest: canonical `mg8_version=1.0` resource-binding envelope, one GST resource in this profile. Each G8SON file has 1-3 gates. Paths stay within the unit directory; ambiguous profiles, unsafe paths and unsupported semantics are rejected.

ORK is JSON with `ork_profile=mg8-runtime-sequential/0.1`, a `bonit` resource reference, and a `flow` listing every required gate exactly in declared execution order. BONIT is JSON with `bonit_profile=mg8-runtime/0.1` and explicit actor/scope/budget declarations. These are this runtime's profile identifiers, not universal format version claims.

A run freezes detached source/policy snapshots. Editing an input file does not hot-reload active policy. An approved revision must go through the host policy revision boundary, invalidating old proposals and permits. External mutable artifact receipts require a domain-specific binding/verification adapter.

## Callback configuration

Registry fingerprints include declared evaluator versions, inspectable implementation code, and inspectable JSON-like values in defaults, keyword defaults, closure cells and directly referenced globals. A changed captured configuration invalidates existing authority. Operation adapters use the same fingerprinting and are rechecked before dispatch. Callback processes receive detached context; a callback cannot mutate the proposal by editing that context.

This is change detection, not a lock or a universal dependency freezer. Opaque objects (including bound-method instance state), indirect helper dependencies, modules, external services and environment-dependent semantics still require immutable, explicitly versioned host configuration and pinned dependencies. Do not mutate callback configuration concurrently with admission or dispatch. Changing an opaque dependency without changing its declared version is outside the enforced boundary. A code/configuration fingerprint is not proof of a semantic assessment.

## Failure and recovery

Reopen the same database to recover committed state and existing permits/events. Interrupted local transactions roll back. Callback serialization/startup failures are recorded as unresolved evaluations rather than leaving an EVALUATING record. Worker callback execution is deadline-limited; trusted host serialization and process creation are not sandboxed or covered by that worker deadline. Do not automatically rerun an interrupted model or remote operation to fabricate evidence. Parent-process death can still leave a proposal EVALUATING; it cannot issue authority, and a new bounded proposal can be evaluated under the same state version. An IN_FLIGHT effect requires explicit host reconciliation before further action; the runtime does not auto-dispatch it again. A late worker result cannot overwrite a reconciled outcome; the conflicting result is audited separately.

QSON exports are verified snapshots of the authoritative append-only database ledger. Re-exporting does not change stored event history. Archive exports per run when preserving separate external evidence files.
