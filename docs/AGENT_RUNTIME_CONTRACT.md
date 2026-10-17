# MG8 agent proposal / runtime commit contract

Status: PROPOSED execution profile, version 0.2. This document specifies enforcement requirements; it does not claim the current engine implements them. No runtime or canonical schema is changed by this document. Revision 0.2 aligns condition evaluation with NYCH's existing AtomicRequirement/evaluator boundary and preserves requirement-style G8SON.

Authorship and provenance of the underlying MG8 file family remain with Nicholas Hartman / American Milestone Inc. This proposal does not replace its canonical specifications.

## 1. Purpose and governing distinction

An agent proposes work. The runtime evaluates the conditional logic defined in the active G8SON files and alone authorizes state commits and controlled effects.

G8SON gates compose authored conditions, including natural-language atomic requirements, through declared logic operators. A model may propose content or supply a declared assessment; it cannot unilaterally authorize its own result. This profile initially supports AND, OR, NAND, and NOR. Additional Boolean operators require explicit, versioned semantics and tests before adoption.

When every input is Boolean, these operators have ordinary Boolean semantics. When evidence is unresolved, evaluation retains an unresolved value; it does not invent a Boolean fact. Final admission is Boolean: only a resolved true authorizes the declared commit. Unresolved admission denies authorization without asserting that the underlying proposition is false.

This is deterministic governance for declared inputs, not a guarantee of deterministic LLM inference, identical external observations, or byte-identical run IDs/timestamps.

## 2. File responsibilities and compatibility

- `.mg8`: binds a bounded unit to its controller, state, gates, and trace resources.
- `.gst`: state, context, constraints, and expectations; model beliefs and observations remain distinguishable.
- `.tcta`: declared trajectory-constraint machinery and parameters; narrows admissible candidate transforms without replacing G8SON acceptance gates.
- `.g8son`: authoritative conditional predicates, logic operator, stable gate identity, and declared outcome routing.
- `.ork`: position, sequencing/control, bounded loop frames, and controller provenance under the declared supported profile.
- `.bonit`: domain authority, actor roles, workflow, operation permissions, required gate coverage, and validation rules. It does not silently replace or duplicate G8SON condition expressions.
- `.qson`: append-only evidence of attempts, evaluations, routes, effects, and commits.
- `.mg8pk` / `system.ork`: composition of multiple units when a supported package profile is explicitly declared.

Canonical G8SON permits strings or objects in `conditions` and leaves operator/predicate semantics to an execution profile. Historical MGate Keeper files use `atomic_requirements` with `req_id` and `requirement`. Both are valid design inputs to this contract. An explicit compatibility adapter MUST preserve original wording, IDs, source bytes/digest, and source profile rather than silently rewriting the files. An adapted representation is separately identified; it does not claim the historical source already conforms to the newer canonical envelope.

Condition evaluation binds to NYCH's existing `AtomicRequirement.evaluate` boundary: an evaluator returns an outcome and reason for the authored requirement. Structured predicates are one optional evaluator implementation, not a mandatory replacement language. The registry/binding fields proposed below are not already standardized or implemented throughout the file family.

The current engine's JSON gate-order list and the MG8 repository's ORK reference profile v0.3 are distinct. An implementation MUST name the profile it supports. This document does not silently migrate existing ORK, QSON, MG8, or legacy ADSR/TOTE artifacts.

## 3. Authority and trust boundary

The agent MAY submit a proposal containing:

- proposal identity, unit/run/step identity, and the expected base state version/digest;
- proposed state changes limited to the current task's writable paths;
- requested operations and their typed arguments;
- evidence references, explanations, and explicitly labeled model assessments.

The runtime MUST NOT accept an agent's `gate_result`, `result`, `transformed`, success wording, claimed observation, or requested next step as authoritative evaluation or permission.

Runtime-owned data includes the active policy/gate digests, observed tool receipts, admission decisions, committed state/version, controller position, loop counters, and QSON event allocation. Proposal fields MUST NOT overwrite these namespaces. Agent references to evidence are not trusted receipts by themselves.

A proposal may contain model-generated evidence, but its provenance MUST remain `model`, not `tool`, `human`, or `runtime`. Model interpretation may inform declared review steps; it does not satisfy a condition requiring an independently observed tool result.

Enforcement requires capability isolation: governed agents cannot directly write committed GST/controller files, alter active gates, forge receipts, or invoke protected effects outside the runtime. Without that isolation this is advisory, not enforceable governance. Sandbox edits are permitted only within explicitly bounded workspaces, not the authoritative state store.

## 4. Freeze the execution contract before evaluation

Before a governed step, the runtime MUST:

1. Validate the selected schemas AND supported profile versions.
2. Resolve resources within the approved unit/package boundary; reject escapes, unresolved references, and ambiguous or duplicate gate identities.
3. Freeze the unit, BONIT, ORK, G8SON, applicable TCTA profile, schemas, evaluator bindings, and operator implementation versions by digest or immutable reference.
4. Resolve the exact required gate set and its declared order/dependencies. Reject skipped required gates, missing routes, unsupported operators, and accidental implicit execution of every available gate.
5. Establish the base GST version and separate immutable input/proposal/evidence snapshots.
6. Validate finite iteration, retry, operation, and evaluation budgets. Model calls and awaited tools require real cancellation/deadline handling, not only a deadline checked between unbounded awaits.

An agent may author candidate gates in an authoring workflow, but those are not the active gates for admitting that same proposal. Activation requires a separately authorized, audited policy revision. A missing profile adapter is a configuration error and blocks execution. A missing requirement evaluator yields UNKNOWN with a reason, matching NYCH's existing boundary; it never supplies an implicit PASS callback. An UNKNOWN requirement blocks admission unless the declared gate logic resolves from other sufficient inputs as specified below.

## 5. Conditions originate in G8SON

### 5.1 Preserve requirements; bind evaluators

The authoritative conditional content comes from the frozen G8SON source, not an independently invented runtime checklist. Each atomic requirement retains its source identity and wording. An approved evaluator binding identifies:

- source file/gate/requirement identity and digest;
- evaluator reference, implementation version, and parameter values;
- evaluation class: mechanical, semantic/model-assessed, or human-review;
- permitted input paths, evidence kinds, freshness rules, and candidate binding;
- acceptance criteria, unresolved behavior, deadlines, and cost/iteration bounds.

Bindings may be declared in profile extension fields on G8SON condition objects or in an explicitly referenced approved registry keyed by exact source identity. The runtime resolves only allowlisted registered evaluators; a file-supplied reference is not permission to import arbitrary code. Bindings implement the authored condition and MUST NOT weaken or silently substitute its meaning. A material reinterpretation is a separately authorized, versioned gate revision.

The existing NYCH callable outcome/reason interface can be wrapped by a runtime-owned receipt recorder; this document does not claim that interface currently returns all required evidence metadata. Record the input and implementation digests, original outcome/reason, evidence references, assessment method, and canonical mapped outcome. An unexpected return value or exception yields UNKNOWN plus a runtime diagnostic, not PASS.

Mechanical requirements use deterministic validators over fixed artifacts. Semantic requirements such as "scientifically accurate" or "reads simply" retain their authored meaning and require a declared assessment procedure. Do not silently replace them with word-count, keyword, or readability heuristics. A declared model assessor may contribute an assessment whose provenance remains model-derived; accepting it is an explicit policy decision, not proof of external truth or deterministic inference. Missing assessment, prohibited self-assessment, or missing required review yields UNKNOWN. Human review is similarly bound to the exact candidate and gate revision.

Changing the evaluator, prompt/rubric, parameters, required reviewer, or evidence policy invalidates previous evaluations. A caller cannot present its own evaluator claims as if the runtime independently executed them.

### 5.2 Separate content, control, and context dependencies

A historical requirement may express content acceptance, a control instruction, or a context dependency. Preserve all three; do not pretend they are interchangeable predicates.

In the inspected `photosynthesis2.g8son`, R1-R3 express content requirements, R4 declares the all-true exit / any-false repeat rule, and R5 requires consulting GST. An explicit reviewed adapter can bind R1-R3 to evaluators, represent R4 as AND with declared repeat/exit routing, and bind R5 to the frozen GST dependencies and any additional acceptance requirements it contains. The runtime MUST NOT guess this translation for arbitrary prose. Record the reviewed mapping and source digest, retain R4/R5 identities in the trace, and make the exit destination unambiguous.

Any GST dependency affecting acceptance MUST be resolved before admission. Encountering "check GST" after an apparent all-true result cannot bypass additional GST constraints. This example demonstrates the required adapter behavior, not permission to rewrite the historical gate files or assume an existing generic prose compiler.

### 5.3 Optional structured mechanical predicates

The following proposed grammar is one mechanical evaluator profile, alongside natural-language requirements with declared evaluators:

- `path`: a JSON Pointer into the frozen evaluation context;
- `op`: `eq`, `ne`, `gt`, `gte`, `lt`, or `lte`;
- `value`: the comparison literal;
- `evidence_kind`: optional required provenance for the resolved value.

The context has three disjoint roots:

- `/current`: committed GST snapshot;
- `/candidate`: proposed next-state snapshot, constructed without mutating `/current`;
- `/evidence`: runtime-verified receipts scoped to this proposal and step.

Path resolution MUST NOT fall back across roots. Candidate values may express proposed content, but a field such as `/candidate/tests_passed` is not proof that tests ran.

Mechanical comparison and Boolean-composition operators MUST NOT use arbitrary `eval`, shell execution, network access, or provider calls. Separately declared semantic assessment or evidence collection may use an authorized adapter under its own recorded policy. Numeric comparisons use a declared exact finite-number representation with explicit size/precision bounds; implicit string/number/Boolean conversion, NaN, and infinity are forbidden. Equality is type-sensitive (`true` is not the number `1`), with no implicit normalization. String equality is exact. Object/array comparisons are rejected in this optional mechanical profile.

A structurally invalid predicate, unsupported operator, or unknown gate type rejects the contract before executing the step. A valid predicate whose input is absent, stale, conflicting, wrong-typed, or has insufficient provenance evaluates to U with a recorded reason. A verified comparison evaluates to T or F. Missing data is not false; in particular, NAND/NOR must not turn missing evidence into a passing result by treating it as false.

External collection is separate from evaluation. A tool adapter collects a receipt under declared permissions and binds it to proposal ID, operation ID, state/input digest, tool identity, and relevant artifact digest. An artifact changed after verification invalidates the associated evidence. An LLM may request a tool call; it cannot mint its receipt.

### 5.4 NYCH, TCTA, TOTE, and HDRP integration

NYCH supplies typed symbolic/context information and the requirement/evaluator boundary. Preserve observed, modeled, intended, executed, and postcondition provenance rather than treating one modality as evidence for another. Machine B's current structural checks do not replace domain requirement evaluators or prove semantic truth.

When the active workflow declares TCTA narrowing, the runtime evaluates the supplied candidate transforms against the active domain constraints before selection. Record the candidate set, constraint/evaluator versions, excluded candidates with reasons, and the admissible survivors. An unenumerated candidate set or an UNKNOWN constraint is not evidence of global admissibility. Unknown candidates remain separately unresolved, not silently accepted or falsely recorded as disproved. Existing Boolean-only TCTA checks require an explicit tri-state adapter where incomplete evidence is possible.

Transforms used for admissibility MUST be pure or evaluated in an isolated staging context. Compute and validate the same candidate result that will later be considered for acceptance; do not execute an effect once for checking and again for committing. Validate finite numeric inputs, valid measure ranges, and threshold ordering before using SPREAD or algorithm selection. A caller's claimed method name alone does not prove execution of that method.

TCTA narrowing does not replace a G8SON condition or grant commit permission. A candidate must survive the declared admissibility stage AND satisfy its required G8SON gate logic. If a required narrowing stage is UNRESOLVED, the controller routes to review or declared bounded continuation; it does not bypass narrowing merely because downstream output looks plausible. Do not require TCTA/HDRP in workflows that do not declare them.

HDRP may rank or predict continuation within an admissible set under an explicitly identified equation/profile version. A prediction is not an observed result or a permit. Stage adaptive gate/error state as well as state registers where rollback is required; a predictor's `step()` may mutate internal state even when register advance is separate. Prefix stability and family separability remain domain-specific evidence obligations, not universal facts supplied by the file format.

TOTE definitions supply the declared TEST/OPERATE/TEST/EXIT process and bound. TEST uses the bound G8SON condition evaluators, OPERATE produces a staged candidate or separately authorized effect, and the next TEST evaluates the resulting evidence. A stored `max_iterations`, a simulated iteration counter, or a database EXIT label is not an executed bound or a verified postcondition. Resolve conflicting loop limits before execution and reject ambiguous limits rather than silently choosing a convenient one. Any repaired candidate passed to the next gate and the commit barrier MUST be the exact candidate that was successfully retested.

## 6. Logic gate semantics

Let T = resolved true, F = resolved false, U = unresolved. Predicate inputs feed the operator named by G8SON `type`.

- AND: F if any input is F; T if all are T; otherwise U.
- OR: T if any input is T; F if all are F; otherwise U.
- NAND: NOT(AND(inputs)).
- NOR: NOT(OR(inputs)).
- NOT(T) = F; NOT(F) = T; NOT(U) = U.

This profile uses nonempty condition arrays or explicitly adapted nonempty atomic-requirement lists. AND/OR/NAND/NOR accept one or more inputs using the rules above. Composition is deterministic and side-effect free for fixed evaluator results; every condition's value and provenance is recorded even where a decisive input determines the result. Semantic/model-assisted inputs may vary between assessments without changing the Boolean composition rules.

Two-input truth table:

| A | B | AND | OR | NAND | NOR |
|---|---|-----|----|------|-----|
| T | T | T | T | F | F |
| T | F | F | T | T | F |
| T | U | U | T | U | F |
| F | T | F | T | T | F |
| F | F | F | F | T | T |
| F | U | F | U | T | U |
| U | T | U | T | U | F |
| U | F | F | U | T | U |
| U | U | U | U | U | U |

A decisive result can coexist with irrelevant unresolved inputs: OR(T,U)=T and AND(F,U)=F. This is logic, not promotion of U. Whether those unresolved inputs must independently be resolved is a separate explicitly declared required gate, not a hidden exception to the operator.

Runtime mapping to canonical G8SON/QSON gate results:

- T -> PASS
- F -> FAIL
- U -> INTERMEDIATE

Internal UNKNOWN may be represented as U and exported as INTERMEDIATE, preserving its original status and reason in evidence. It MUST NOT become PASS. ORK bound exhaustion remains controller outcome UNRESOLVED; it is not silently rewritten as a false predicate or a canonical gate-result enum value.

## 7. Example G8SON admission logic

The first example preserves authored requirement text inside canonical G8SON condition objects and attaches proposed evaluator references. Those references are illustrative registry entries, not functions already present in the repository. Approval of the bindings is required before execution. The source requirement-style files remain unchanged.

```json
{
  "g8son_version": "1.0",
  "file_id": "photosynthesis.structure.adapted",
  "gates": [
    {
      "gate_id": "G_STRUCTURE",
      "type": "AND",
      "conditions": [
        {"req_id": "R1", "requirement": "Use this word formatting : Subject (the term being defined) then definition", "evaluator_ref": "photosynthesis.subject_definition@1"},
        {"req_id": "R2", "requirement": "Definition should read simply", "evaluator_ref": "photosynthesis.simplicity_review@1"},
        {"req_id": "R3", "requirement": "Response must strictly stay to formatting and not add extra wording", "evaluator_ref": "photosynthesis.format_only@1"}
      ],
      "outcomes": {"PASS": "check_context", "FAIL": "repeat", "INTERMEDIATE": "review"}
    }
  ],
  "metadata": {"execution_profile": "agent-proposal-runtime-commit/0.2"}
}
```

This is a partial adapter illustration, not a complete executable reproduction of the historical gate. `check_context` must resolve R5/GST dependencies and any other required gates before admission; R4's reviewed control mapping must be recorded. `repeat` requires a finite declared ORK bound. The simplicity evaluator needs an approved rubric/assessment policy; its name alone establishes no pass condition.

The second example uses the optional mechanical predicate profile. It is not an assertion that today's executor understands these operators or predicate fields.

```json
{
  "g8son_version": "1.0",
  "file_id": "agent.change.admission",
  "gates": [
    {
      "gate_id": "verified_change",
      "order": 1,
      "type": "AND",
      "conditions": [
        {"path": "/evidence/scope/allowed", "op": "eq", "value": true, "evidence_kind": "runtime"},
        {"path": "/evidence/tests/exit_code", "op": "eq", "value": 0, "evidence_kind": "tool"},
        {"path": "/evidence/tests/artifact_matches_candidate", "op": "eq", "value": true, "evidence_kind": "runtime"}
      ],
      "outcomes": {
        "PASS": "commit",
        "FAIL": "reject",
        "INTERMEDIATE": "review"
      }
    }
  ],
  "metadata": {"execution_profile": "agent-proposal-runtime-commit/0.2"}
}
```

`scope.allowed` and `artifact_matches_candidate` are runtime-derived receipt fields; the agent cannot set them. Policy determines the approved test commands. The test adapter records the actual exit code and binds the receipt to the tested candidate, rather than accepting agent-submitted command output.

For OR, any declared alternative suffices. For NAND, at least one resolved false input disproves the conjunction. For NOR, every input must be resolved false. Their conditional expressions remain in G8SON; the runtime supplies operator implementations, not hidden substitute requirements.

## 8. Route results; do not merge outputs

The runtime MUST select the declared route for the computed result. Initial route meanings:

- `continue`: proceed to the declared next gate/step without committing candidate state.
- `commit`: request admission to the commit barrier; it does not bypass that barrier.
- `reject` or `stop`: end the current proposal without a candidate-state commit.
- `review`: suspend admission and request declared additional evidence/review.
- `repeat`: repeat only under the active finite ORK loop/retry bound.

Labels are profile-defined and validated before execution. No implicit fallthrough is permitted. Required gate coverage comes from the frozen workflow: an early PASS route cannot skip a required verification gate. An intentionally optional alternative is declared as such, rather than inferred from an omitted flow entry.

A failed proposal may lead to a separately authorized recovery task. Failure does not authorize copying its candidate fields into committed state. Updating the audit/controller to record a rejection is distinct from accepting the proposed domain-state transition.

## 9. Commit barrier

A candidate-state commit is authorized if and only if all of the following hold:

- The proposal and actor are valid for the active run, unit, step, and capability scope.
- The expected base state/version still matches the current authoritative state.
- Active policy and gate versions still match the frozen evaluated versions.
- Every required admission gate has a runtime-computed PASS for the exact candidate/evidence set being committed.
- Required evidence is complete, correctly sourced, fresh under declared rules, and bound to the exact candidate artifacts and operation identities.
- The selected route authorizes this transition and no stop/cancellation or bound exhaustion superseded it.
- The commit has not already been applied, and durable audit/transaction preparation succeeds.

These are fixed runtime integrity checks. They do not replace domain conditionals in G8SON. Where a domain fact must control admission, express it as a G8SON condition; where a fact protects the integrity of the evaluator itself, enforce it in the runtime and record the check.

The runtime MUST recheck base version, cancellation, artifact binding, and policy version at the linearization point, not only when evaluation started. A stale proposal is rejected or explicitly rebased and reevaluated; it is never silently applied to newer state.

A single authorized transaction publishes the new GST version, the corresponding controller transition, and a durable commit identity/evidence record. If storage cannot atomically cover those resources, use a recoverable journal protocol with prepared/committed states and deterministic replay. Do not report commit success for a partially published transaction.

Rejected and INTERMEDIATE attempts preserve the committed domain state. Their audit evidence is still appended.

### 9.1 ActionPermit is an enforced capability, not a verdict string

Use NYCH's ActionPermit concept as the integration boundary; its current dataclass methods alone are not sufficient enforcement. A runtime-owned durable permit store MUST bind each permit to the exact proposal/candidate, run/unit/step, actor, operation scope, base-state version, gate/evaluator/policy digests, semantic/provenance digest, epoch, and expiry where applicable.

Issuance requires the corresponding admission checks. Consumption atomically transitions ISSUED to CONSUMED with the authorized local transaction or durable external-operation dispatch record. A permit cannot authorize a different candidate or operation, be consumed twice, or remain valid after revocation/expiry. An immutable dataclass can remain a snapshot, but cannot be the sole authoritative lifecycle store. Concurrent consume/revoke requests require one serialized winner.

The consume barrier revalidates every binding, actor, cancellation state, and authoritative permit lifecycle. A state/policy/semantic revision invalidates affected permits; revoked permits never become valid merely because an old hash happens to match. Canonical, versioned serialization defines hash inputs; Python `str(dict)` is not the canonicalization contract. Never advance a repaired candidate using a permit bound only to the original candidate.

Record issue/consume/revoke/expire evidence through canonical QSON event types with explicit operation/reason metadata; do not invent new canonical event enum values. An external-operation retry refers to the same durable operation record and idempotency policy, not a second consumption of the permit.

## 10. External effects require a separate boundary

A local transaction cannot atomically roll back arbitrary remote APIs, Git pushes, messages, or physical actions. Do not claim universal exactly-once execution.

The runtime MUST distinguish:

1. pre-effect authorization gates over current state, proposal, and available evidence;
2. authorized dispatch through a capability-limited adapter;
3. collection of the actual effect receipt;
4. post-effect verification gates, defined in G8SON;
5. recording the verified outcome and any authorized state transition.

A postcondition is not required to exist before its own operation; a pre-effect approval is not evidence that the effect happened. Use isolated staging for reversible local edits when applicable. Changes produced by staging are not authoritative commits.

Use operation identities and downstream idempotency keys where supported. After a crash or timeout with an unknown remote outcome, record ambiguity and reconcile before retrying. If an effect happened but verification failed, record the observed effect and failed/INTERMEDIATE verification; do not invent rollback or conceal it. Compensation, if permitted, is a new authorized and audited operation.

## 11. Audit and recovery

Every attempted gate receives a distinct trace_id. QSON uses the canonical `events` envelope, unique increasing sequences per run, structured actor identity, and explicit event types. Record:

- proposal/run/unit/step identities and base state;
- gate file/gate identities and immutable versions;
- predicate source, resolved values, T/F/U results, provenance, and unresolved reasons;
- operator result, canonical result, and selected route;
- requested/dispatched operations and actual receipts;
- rejection, review, cancellation, timeout, bound exhaustion, and runtime errors;
- successful state_commit events with input/output state identities;
- explicit policy changes, overrides, corrections, and superseding references.

Append corrections rather than rewriting prior decisions. Review does not change an old FAIL or INTERMEDIATE into PASS. New evidence causes a new attempt. This profile does not allow an override to bypass unresolved required admission gates; an authorized policy revision is a separately traced version change requiring fresh evaluation.

A schema-valid event is not enough: enforce run consistency, sequence uniqueness, required gate-event linkage, and event-specific evidence requirements. Trace persistence is part of the protocol; an in-memory list or an empty trace file is not a durable ledger.

Recovery replays committed transactions idempotently, distinguishes prepared transactions from committed ones, and reconciles uncertain external effects. Never rerun a model/tool merely to manufacture a missing success record.

## 12. Minimum conformance tests

A conforming implementation MUST demonstrate:

1. All nine two-input combinations above for each operator; Boolean-only cases match ordinary Boolean logic.
2. Missing, conflicting, wrong-typed, and stale inputs remain U unless the declared operator has a decisive result from other inputs.
3. An agent's PASS/transformed assertion cannot override a computed FAIL or INTERMEDIATE.
4. Gate conditions are taken from the frozen G8SON file, not replaced by prompt text or callback claims.
5. FAIL and INTERMEDIATE do not commit candidate state or dispatch protected effects.
6. OR/NAND/NOR are not silently treated as AND; all required gates and routes execute as declared.
7. A changed gate/policy, changed artifact, concurrent state revision, or cancelled run invalidates prior admission.
8. A late callback cannot commit after cancellation or alter a newer run's controller.
9. Missing callbacks, unsupported operators/versions, duplicate identities, and unsafe references fail closed.
10. Every retry is a separate event; exhaustion yields UNRESOLVED without a candidate-state commit.
11. Crash injection at each commit-journal boundary never produces an acknowledged unaudited commit, a duplicate local commit, or an unrecorded ambiguous external effect.
12. Actual persisted QSON validates structurally and semantically, including increasing sequences and retained rejected attempts.
13. Original requirement text and IDs survive adaptation; an unbound natural-language requirement is UNKNOWN, not discarded or replaced by an unrelated heuristic.
14. Semantic assessment and human review remain bound to their declared rubric, evaluator/reviewer identity, candidate, and provenance. They cannot forge tool observations.
15. Historical control/context requirements such as R4/R5 resolve to reviewed routing/dependencies; no apparent exit skips GST-dependent checks.
16. A permit cannot be consumed twice, consumed after revoke/expiry, used for a different action/candidate, or replayed across epochs. Race/crash tests exercise its durable store.
17. Repaired candidate state and evidence propagate consistently through later gates and commit. No gate verifies one state while the runtime commits another.
18. Required TCTA narrowing cannot be bypassed by HDRP ranking or a model's admissibility assertion. Stateful/effectful transforms cannot run during a purported pure check; invalid numeric inputs are rejected.

## 13. Implementation boundary in this checkout

At local baseline c44ca2fac1849d973b65c9996a7d39ed586ea6e6:

- `ork.py:_infer_gate_result` accepts callback verdicts and transformed flags; this contract instead requires runtime predicate/operator evaluation.
- `ork.py:execute_ork` directly merges callback fields and does not enforce ordinary gates' outcomes; this contract requires staging, routing, and the commit barrier.
- The implicit dummy PASS callback is a reference/test behavior, not permitted production admission.
- Canonical QSON persistence and current reference `entries` objects need an explicit compatibility/export decision, not a silent rename/migration.
- Full ORK/BONIT parsing and package composition remain separately declared implementation work.

Cross-repository inspection at NYCH `cee3610723ffe4877c424591711fed29717ab655` and TCTA `f2882c131e3e220d1cf1c9b7448625aabd51a85f` establishes existing reusable mechanisms, not complete enforcement of this contract:

- NYCH `AtomicRequirement` accepts requirement text plus an evaluator; unbound requirements return UNKNOWN. `GateDefinition` currently hard-codes conjunctive aggregation, not the full operator catalog.
- NYCH's ActionPermit consume/revoke methods currently return success without changing authoritative lifecycle state; issuance does not by itself secure an effect boundary.
- NYCH's prototype repair state must not be assumed to propagate into later gates or final committed state without verification.
- TCTA implements candidate filtering, SPREAD/routing, compliance checks, numeric HDRP, and a file parser. Domain evaluators and Gamma/Psi remain supplied per domain; compliance claims are not receipts proving actual computation.
- TCTA HDRP and HDRP-main's historical-core equations/initialization are distinct profiles and must not be silently interchanged.
- T.O.T.E-loops supplies database/process definitions, not a generic executing controller.

Historical MGate Keeper demonstration evidence is preserved separately: the inspected photosynthesis QSON contains two response contents with distinct recorded response IDs, identical 152-byte UTF-8 payloads, and SHA-256 `4dc08fdc7268caa3362bb78296ca458b867c4a3551976d785dff579f3a61f252`. This is a verified stored-output match, not a fresh rerun, proof of each requirement's satisfaction, or a universal inference-determinism guarantee. A new reproducibility test must append separate evidence and preserve the historical ledger and original request-construction behavior for comparison.

This document authorizes no automatic migration, source refactor, provider calls, or external effects. Implementation should proceed through small regression-tested changes while preserving historical profiles explicitly.

## Sources inspected

- MG8 / ORK / MG8PK: https://github.com/nhartman000/mg8/tree/bd5fcee17a1b4173c39f92de46783c52cfb13f71/spec
- G8SON logic/operator and condition profile requirements: https://github.com/nhartman000/g8son/blob/ecb193d90189c8bfdb2d0e7cebb00432a1d0e260/spec/g8son_v1.md
- G8SON envelope schema: https://github.com/nhartman000/g8son/blob/ecb193d90189c8bfdb2d0e7cebb00432a1d0e260/schema/g8son.schema.json
- GST: https://github.com/nhartman000/gst/blob/0d8aefbede38a6e9e8ec671ef9a135d491147ff2/spec/gst_v1.md
- QSON: https://github.com/nhartman000/qson/tree/92e6e3e8f9f0fa4f501db21228116417d71df998
- NYCH requirement evaluation, orchestration, and permit implementation: https://github.com/nhartman000/nych/blob/cee3610723ffe4877c424591711fed29717ab655/nych/gates.py
- TCTA implementation: https://github.com/nhartman000/TCTA/tree/f2882c131e3e220d1cf1c9b7448625aabd51a85f/src/tcta_engine
- TCTA file-role specification: https://github.com/nhartman000/TCTA/blob/f2882c131e3e220d1cf1c9b7448625aabd51a85f/spec/tcta_file_format_v1.md
- T.O.T.E-loops: https://github.com/nhartman000/T.O.T.E-loops/tree/cad966090296130493ec6d84c3ed8de998524aa1
- HDRP historical-core profile: https://github.com/nhartman000/HDRP/blob/f5d26f47f8a8885dff63d84cb766d8ff152606b9/docs/HDRP_FORMAL_SPECIFICATION.md
- Historical local evidence, inspected read-only: `/home/deepsleep_r/Code/mgate-keeper4/mgate-keeper/demo2_reproducible.py`, `mgate_keeper/projects/g8son/photosynthesis2.g8son`, and `mgate_keeper/projects/qson/photosynthesis.qson`.
