# Security boundary

This release is a host-owned reference runtime, not an operating-system sandbox or a hosted authorization service.

## Trusted components

The orchestrator, SQLite database, registry registrations, evidence collectors, operation adapters, reviewer approvals and policy revisions are trusted host capabilities. Untrusted agents must receive only a constrained message interface and isolated workspace. They must not have access to Runtime, Store, registry internals, the database/WAL files, or protected effect channels. AgentSession is a convenience facade, not protection against Python introspection.

Never load serialized Python or cloudpickle bytes from agent input. The runtime uses cloudpickle only to transfer its own host-registered callbacks to spawned worker processes. Callback workers enforce deadlines and isolate accidental in-memory mutations; they inherit host access and are not safe sandboxes for hostile Python code. Review and version callbacks before registration. Network credentials or environment variables accessible to those workers remain host responsibilities.

## Guaranteed checks within that boundary

- State scope, actor identity supplied by the host session, base version and policy epoch are checked before admission.
- All required gate reports and their declared routes must authorize the transition.
- Evidence changes and expiry invalidate a prior evaluation; receipts are scoped to the exact proposal/candidate.
- Permits are consumed transactionally, not via mutable agent assertions.
- Cancellation and concurrent commits invalidate stale authority.
- SQLite state and audit changes share a transaction. SQL triggers prevent ordinary event UPDATE/DELETE/REPLACE. Hash chains detect accidental/in-scope ledger tampering, not a database owner who rewrites the whole database and its hashes.

A registered semantic evaluator's PASS is a declared assessment, not mathematical proof of truth. Preserve its provenance and require independent observations/review where the policy demands them. Caller-authored provenance in ordinary candidate fields is not a trusted tool receipt.

Fingerprints detect changes to inspectable JSON-like callback defaults, closure values and directly referenced globals, as well as registered versions/code. Opaque objects, bound-method instance state, indirect helper dependencies, environment variables and remote services must remain immutable/versioned host dependencies. Fingerprinting is not a lock against concurrent trusted-host mutation. See `docs/IMPLEMENTATION.md` for the precise boundary. Worker serialization/startup errors fail unresolved; the worker execution deadline does not bound arbitrary trusted host serialization or OS process creation.

## External effects

Dispatch is recorded durably and the permit consumed before a registered adapter runs. A crash in the dispatch window leaves an IN_FLIGHT record. A timeout or exception is UNKNOWN because effects may already have occurred. Inspect the actual downstream system, then reconcile the existing operation. Do not blindly retry or create a replacement proposal to conceal an unresolved effect. Downstream idempotency keys and compensations are adapter-specific; universal exactly-once remote execution is not claimed.

Only a single controlling host should perform recovery/reconciliation for a run. SQLite serializes commits; it does not provide distributed ownership of arbitrary remote systems.

Reconciliation is authoritative over a late worker completion. A late adapter return is retained in a separate audit event and cannot replace the reconciled operation record or its receipt.

## Operational recommendations

Use a private host-owned directory, separate OS identities or containers, narrowly scoped adapter credentials, and a staged artifact workspace. Pin evaluator dependencies and external observations. Export the canonical ledger to a separate evidence store when stronger tamper resistance is needed. Avoid placing secrets or personal data in proposals, reasons or receipts because QSON intentionally preserves them.

Local callback execution and storage were tested on Linux. Other operating systems and real provider adapters require separate validation. Report defects privately through GitHub's security reporting feature if available, or contact the repository owner without posting credentials or sensitive evidence in public issues.
