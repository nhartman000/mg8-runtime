# Offline NYCH → M-Gate → MG8 Runtime → QSON integration

**Implemented and mechanically demonstrated; no model-inference claim.**
The input is an authored fixed sentence, not a fabricated model response. No
provider, paid model, network service, general task compiler, NYCH full pipeline,
TCTA admissibility adapter, or full three-gate trajectory search is exercised.

## Install and run

Install a separately built NYCH wheel **including `nych.schemas`** and this
runtime wheel with its `integration` extra. Publication CI pins NYCH to
`57b81e9220069dd5ff72197b41288c9613e3343b` (merged NYCH PR #3).
The older baseline `cee3610723ffe4877c424591711fed29717ab655` omits that
subpackage from wheels; an editable install of it is not clean-install evidence.

```sh
python -m pip install /path/to/nych-0.2.0-py3-none-any.whl \
  '/path/to/mg8_runtime-0.1.0-py3-none-any.whl[integration]'
python -m mg8_runtime.nych_demo run ./nych-pass
# A separate process, not a producer success report:
python -m mg8_runtime.nych_verify ./nych-pass
python -m mg8_runtime.nych_demo run ./nych-fail --scenario fail
python -m mg8_runtime.nych_verify ./nych-fail
python -m mg8_runtime.nych_demo run ./nych-unknown --scenario unknown
python -m mg8_runtime.nych_verify ./nych-unknown
```

Each output directory must be new, with an existing parent. All artifacts and
SQLite writes stay in that selected workdir. `accepted.txt` is the sole effect
target; no agent-controlled pathname is joined to an external directory. The
adapter checks its entire argument object and uses exclusive/no-follow creation.
This is a trusted single-host offline example, not a filesystem sandbox or
concurrent hostile-process defense.

## Actual boundaries

1. `nych.semantic_encoding.encode_text` encodes `I see a red light.` with the
   installed NYCH semantic registry. `source.txt` and `encoded.json` preserve
   input, encoded text, decision records and audit summary. The checkpoint is
   protected runtime GST state (`/nych`), not a disconnected sidecar. This is
   the same encoder entry point used by NYCH's `encode` CLI, not `run_pipeline`.
2. The producer writes a bounded `unit.mg8`, `flow.ork`, `policy.bonit`,
   `state.gst`, `commit.g8son` and `effect.g8son`; the real `load_unit` validates
   and freezes the unit. The trusted host copies the loader's state, gates,
   bindings and bounds into `Runtime.create_run`, explicitly extending it with
   the runtime's existing effect policy API. `LoadedUnit.start()` does not accept
   effect policy arguments, so it is deliberately not called or misrepresented.
3. The host registry binds `nych.operation-text@1` to the adapter in
   `nych_adapter.py`. It instantiates and calls the **actual**
   `nych.gates.AtomicRequirement.evaluate()` with an explicit mechanical text
   comparison. Missing proposed text leaves the requirement without an
   evaluator, invoking NYCH's own `UNKNOWN/no_evaluator_attached` behavior.
   NYCH owns that rule/evaluator code; runtime owns admission and enforcement.
4. `Runtime.evaluate(..., phase='effect')` executes the named
   `exact-operation-admission` AND gate in a spawned process. Its conditions
   bind the protected NYCH encoding, exact operation name, basename, text and
   candidate hash. It preserves raw NYCH PASS/FAIL/UNKNOWN in requirement
   evidence and maps UNKNOWN to canonical `INTERMEDIATE` in gate traces.
5. Only `authorize(..., purpose='effect')` plus `dispatch` may invoke the
   allowlisted `demo.write-encoded@1` adapter. A consumed permit and durable
   dispatch record precede the write. The deterministic candidate is a host
   proposal, **not model-generated output**.
6. The host freshly reads the actual file bytes and records a separate tool
   observation. The `fresh-final-state` gate requires both a successful
   operation receipt and the observed SHA256 before a separate commit permit
   can be consumed by `Runtime.commit`. `committed.gst`, `operation.json`,
   `runtime.sqlite` and `execution.qson` retain the result and evidence.
7. The standalone `nych_verify` process independently re-encodes the input,
   reads the real external file and persisted SQLite/QSON/GST itself, validates
   vendored canonical G8SON/QSON schemas, checks contiguous sequence, trace
   uniqueness and hash chain, matches the export to SQLite, replays gate
   conditions with a separately implemented mechanical evaluator, and checks
   exact supported record/event inventory, terminal lifecycles, audited
   transitions and source/policy/candidate/receipt/operation/permit/commit bindings.
   **Independence boundary:** this is an independent persisted-state verifier,
   not an independently reimplemented gate engine. It shares `GateSet`,
   `Registry`, loader and canonical digest semantics with the runtime; the
   small NYCH mechanical comparison is separately implemented. A common-mode
   bug in those shared semantics can therefore affect producer and verifier.
   Existing permits bind candidate identity through the checked evaluation
   digest and proposal; any explicit `candidate_digest` extension must also
   equal the expected candidate (no runtime record/schema migration).
   It does not import the producer/adapter, instantiate Runtime/Store, or trust
   producer stdout. It opens completed SQLite bundles immutable/read-only, not
   live WAL-backed runs. Tests assert the verifier changes no workdir bytes.

The FAIL scenario changes only proposed text; UNKNOWN omits it. Both retain a
nonpassing gate attempt plus actual admission-denial events, never dispatch or
receive a permit, never create `accepted.txt`, and retain version-zero state.
The verifier reports `VERIFIED_BLOCKED` (not task completion). Passing runs
report `VERIFIED_COMPLETE`. Tampered bundles exit nonzero.

## Profiles and identity (no schema migration)

- Host example: **`nych-runtime-one-unit/1`**.
- Manifest: loader-supported JSON `mg8_version: 1.0`; exactly one GST envelope
  with `gst_version: 1.0` and `state`; these are runtime profiles, not a claim
  that every MG8/GST reference grammar is supported.
- ORK: **JSON `mg8-runtime-sequential/0.1`**, an exact ordered gate list, not
  block-syntax ORK v0.3 or a universal ORK parser. No `.mg8pk` graph/archive run.
- BONIT: **JSON `mg8-runtime/0.1`**, explicit actors, writable paths and bounds.
- G8SON: canonical version-1 envelope, AND/OR/NAND/NOR runtime logic, scalar
  JSON Pointer predicates plus host evaluator references and explicit outcome
  routes. This example uses AND only. Natural-language requirements are not
  automatically compiled to acceptance rules.
- QSON: canonical version-1 envelope/events, verified against the unchanged
  schema pinned in [SOURCES](SOURCES.md). Runtime-specific evidence and
  `previous_event_hash`/`event_hash` fields fit that schema's extension points.
  Runtime JSON digest profile is **`mg8-runtime-json/1`**, not an unqualified
  canonical-format hash algorithm. UNKNOWN is serialized as INTERMEDIATE.
- Source identity includes original resource byte hashes, distribution
  versions, and SHA256 of installed NYCH `gates.py`, `semantic_encoding.py`,
  `semantic_registry.py` and `data/sense_registry.json`. The verifier checks
  those against its installed encoder and the initial ledger event. NYCH
  distribution version 0.2.0 differs from its module `__version__` 1.2.0;
  distribution metadata is explicitly what is recorded, not a guessed revision.

Determinism here means reproducible encoding, effect bytes and admission for
this fixed mechanical fixture. Run IDs, trace IDs, permits, timestamps and audit
metadata vary; no byte-identical-QSON or deterministic-inference claim is made.
Hash chains detect inconsistent tampering, not a malicious trusted host capable
of rewriting every artifact and the verifier. Source fingerprints are not
signatures, immutable dependency isolation, or proof of semantic entailment.

## Tests and clean-install CI

```sh
python -m unittest discover -s tests -v
python tools/check_wheel_install.py \
  --nych-wheel /absolute/path/to/nych-0.2.0-py3-none-any.whl \
  --output /absolute/new/clean-install-directory
```

The verifier reads canonical schemas with `importlib.resources` from its own
package, so `pip --user`/`--target` imports do not assume `sys.prefix`. The
package-resource copies retain the canonical schema bytes and digests; no
schema semantics change. The legacy `share/` installation remains available.
The test driver builds sdist and wheel, asserts both shipped schema copies match
original bytes, rebuilds the wheel from sdist, creates a fresh virtualenv, installs only
wheels (no editable fallback), checks both imports originate in that environment,
and runs subprocess integration/tamper tests from outside either checkout with
PYTHONPATH/PYTHONHOME/PYTHONOPTIMIZE removed. Acceptance checks use explicit
exceptions, including when the driver itself runs under `python -O`. It persists actual PASS/FAIL/UNKNOWN bundles and a
wheel-hash `result.json`. Installation/build bootstrap may use the network and
NYCH's declared dependencies; the demonstration itself is offline. This is not
an all-transitive-dependencies lockfile claim.

`.github/workflows/nych-integration.yml` provides dispatchable/reusable CI on
Python 3.11–3.14, requiring a full published NYCH commit SHA.
`.github/workflows/nych-pinned.yml` calls it on every push and pull request at
`57b81e9220069dd5ff72197b41288c9613e3343b`; there is no local source override.
The separate normal test workflow continues
to test the runtime without mandatory NYCH dependencies. Local tests explicitly
skip the optional integration when NYCH is absent; clean-install CI installs it
and checks its imports first, so it cannot satisfy integration by skipping.

Regression coverage includes final-byte/GST/NYCH/source/gate/QSON tampering,
SQLite state/operation/receipt corruption, truncated exports, rehashed gate
assessment tampering, and rehashed substitution of effect authority for commit
authority, expired/invalid permit authority (including rehashed issuance records),
as well as FAIL/UNKNOWN and read-only verification. Expiry is checked against
audited issuance/consumption times, never the later verification wall clock.
