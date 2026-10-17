# MG8 Runtime

Runtime-enforced agent proposals, G8SON logic gates, single-use permits, and audited state commits.

Nicholas Hartman / American Milestone Inc.

## What runs

The agent proposes a candidate. The host runtime evaluates the conditions from the frozen G8SON source, applies AND / OR / NAND / NOR, follows declared routes, and checks a durable permit before committing. An agent-supplied `PASS` or `transformed` flag is not permission.

Implemented in this repository:

- three-valued logic with UNKNOWN preserved internally and INTERMEDIATE in canonical gate traces;
- canonical G8SON condition objects plus explicit adapters for requirement-style `atomic_requirements`;
- registered mechanical, semantic/model-assessment, and human-review evaluators;
- immutable proposal snapshots, writable-path scope, evidence provenance and expiry;
- bounded TEST / revise / TEST workflows; a failed candidate is not merged into committed state;
- optional required admissibility evaluator before gate assessment, suitable for a TCTA domain adapter;
- durable permits, revocation, expiry checks, epoch/policy/evidence invalidation and competing-commit protection;
- transactional SQLite state and append-only QSON events, hash-chain verification and atomic export;
- separate pre-effect authorization, one-shot dispatch records, post-effect verification, and uncertain-outcome reconciliation;
- resource-bound MG8 loading for an explicitly named sequential JSON ORK/BONIT profile;
- offline runnable demo, tests, canonical schema checks and CI.

This is an initial implementation profile, not a claim of complete implementation of every MG8-family grammar or of universal deterministic LLM inference. Read [implementation boundaries](docs/IMPLEMENTATION.md) and [security](SECURITY.md).

## Install

Python 3.11 or later:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
```

There are no provider credentials required. `cloudpickle` serializes only trusted host callbacks into deadline-limited spawned processes; serialized agent input is never accepted. `jsonschema` and `build` are test/build dependencies.

## Run the offline demo

```sh
mg8-runtime demo --output ./demo-run
```

The output directory must not exist. The demo preserves authored requirement text, registers explicit evaluators, deliberately submits a failing draft, revises it, obtains PASS, consumes a permit, and commits the accepted candidate. It writes:

- `requirements.g8son` and explicit `bindings.json`;
- `runtime.sqlite`, the authoritative transactional state/evidence store;
- `execution.qson`, a verified canonical ledger export;
- `committed.gst`, a snapshot of the committed state.

The definition is checked against a declared reviewed reference. The demo does not pretend to implement a general scientific-truth evaluator, call a model, or reproduce the historical MGate Keeper experiment.

## Run a resource-bound unit

```sh
mg8-runtime run examples/basic/unit.mg8 \
  --proposal examples/basic/proposal.json \
  --database ./basic-run.sqlite \
  --output ./basic-run.qson
```

The proposal file contains a state object, not trusted receipts or a permission envelope. The CLI's default registry includes mechanical predicates; custom requirement evaluators must be registered by a trusted host integration, never dynamically imported from an agent-supplied reference.

## Host integration

```python
from mg8_runtime.gates import Registry
from mg8_runtime.runtime import Runtime, AgentSession

registry = Registry()
# Host registers approved evaluators before freezing a run's policy.
runtime = Runtime('private/runtime.sqlite', registry)
run_id = runtime.create_run(
    {'answer': ''}, [gate_document],
    actors=['worker'], writable_paths=['/answer'], max_attempts=3,
)
agent = AgentSession(runtime, run_id, 'worker')
proposal_id = agent.propose({'answer': 'proposed text'}, base_version=0)
report = runtime.evaluate(proposal_id)
if report['outcome'] == 'PASS':
    permit_id = runtime.authorize(proposal_id)
    runtime.commit(permit_id)
```

`authorize` also checks required routing, current evidence, policy and state versions; a PASS report alone is insufficient. `AgentSession` exposes proposal/snapshot methods only, but is **not an in-process security sandbox**. Keep the actual agent in a separate restricted process/container without database, host callback or protected filesystem access. All receipt creation, evaluator registration, policy revision and reconciliation methods are trusted-host capabilities.

Application `if` statements above decide when to ask for admission; they do not supply domain acceptance rules. Those rules remain in G8SON. Natural-language requirements remain text plus evaluator bindings; the runtime does not secretly translate "simple" or "accurate" into keyword checks.

### Effects

Register allowlisted operations using `register_operation(name, adapter, version=...)` before creating a run. Such a run requires separate `effect_gate_documents` for pre-effect checks. Evaluate with `phase='effect'`, issue a permit with `purpose='effect'`, then call `dispatch`. The permit is consumed with a durable dispatch record before the adapter executes.

Pre-effect conditions can inspect `/operation/name` and `/operation/arguments/...`, in addition to `/current`, `/candidate` and `/evidence`. The operation envelope is a detached agent proposal, not independently verified evidence; bind any required observations through host-collected receipts.

Evaluate the proposal again in the default commit phase after the actual receipt exists; postcondition gates can reference `/evidence/operation`. A returned adapter value is only a receipt, not proof of all postconditions. Timeouts and exceptions are UNKNOWN because an external side effect may already have happened. They are not automatically retried. A trusted host can independently investigate and use `reconcile_operation` to append a correction. See `tests/test_effects.py` for complete examples.

A worker that finishes after reconciliation cannot overwrite the recorded outcome. Its conflicting late result is retained as a separate audit event.

No automatic remote provider, filesystem-edit, Git-push or messaging adapter is installed. Connecting one is an explicit host capability decision.

## Verify

```sh
python -m unittest discover -s tests -v
python -m build
```

Tests exercise logic, missing evaluators, source preservation, path confinement, real spawned deadlines, cancellation races, failed/unknown admission, single-use permits, concurrent commits, subprocess crash rollback, effect ambiguity and canonical QSON validation. Tests run offline and use temporary storage.

## Formats and provenance

This is a separate runtime implementation. It does not modify existing NYCH, TCTA, MG8-engine, historical gate files, or ledgers. The named JSON ORK/BONIT profile is not the full block-syntax ORK v0.3/BONIT language. `.mg8pk` graph/archive execution and automatic multi-GST merging are deliberately unsupported rather than guessed.

The canonical schemas in `schemas/` are copied unchanged from the author's G8SON and QSON repositories at the pinned revisions in [sources](docs/SOURCES.md). The [runtime contract](docs/AGENT_RUNTIME_CONTRACT.md) is the broader proposed target; [implementation boundaries](docs/IMPLEMENTATION.md) distinguishes the implemented release profile from remaining integration work.

License: Apache-2.0. See [LICENSE](LICENSE).
