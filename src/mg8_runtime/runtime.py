"""Host-owned proposal, evaluation, capability and transactional commit boundary.

Agent code must not receive this object, evaluator registry or database access.
The isolated evaluator process enforces a deadline, not an OS security sandbox.
"""
from contextlib import contextmanager
import math
import multiprocessing
import time
from uuid import uuid4

import cloudpickle

from .canonical import clone, digest, dumps
from .effects import EffectsMixin
from .gates import GateSet, Outcome
from .store import Store


class AdmissionError(ValueError):
    """A proposal/capability is not admissible at this boundary."""


def _identifier(prefix):
    return prefix + '_' + uuid4().hex


def _positive(value, name, maximum=10000):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{name} must be an integer in 1..{maximum}')
    return value


def _pointer_parts(path):
    if not isinstance(path, str) or not path.startswith('/') or path == '/':
        raise ValueError('writable paths must be non-root JSON Pointers')
    parts = path[1:].split('/')
    for part in parts:
        if '~' in part.replace('~0', '').replace('~1', ''):
            raise ValueError('invalid JSON Pointer escape')
    return tuple(p.replace('~1', '/').replace('~0', '~') for p in parts)


def _changed(a, b, prefix=()):
    if type(a) is dict and type(b) is dict:
        result = []
        for key in set(a) | set(b):
            if key not in a or key not in b:
                result.append(prefix + (key,))
            else:
                result.extend(_changed(a[key], b[key], prefix + (key,)))
        return result
    return [] if dumps(a) == dumps(b) else [prefix]


def _worker(connection, serialized_function):
    try:
        function = cloudpickle.loads(serialized_function)
        connection.send_bytes(dumps({'value': function()}).encode())
    except BaseException as exc:
        connection.send_bytes(dumps({'error': f'{type(exc).__name__}: {str(exc)[:500]}'}).encode())
    finally:
        connection.close()


def isolated(function, seconds):
    """Bound host-registered callbacks in a fresh spawn process, never agent code."""
    read, write, process, started = None, None, None, False
    try:
        serialized_function = cloudpickle.dumps(function)
        ctx = multiprocessing.get_context('spawn')
        read, write = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_worker, args=(write, serialized_function), daemon=True)
        process.start()
        started = True
        write.close()
        if not read.poll(seconds):
            return {'error': 'evaluation deadline exceeded; outcome unresolved'}
        import json
        return json.loads(read.recv_bytes(4_000_000))
    except Exception as exc:
        return {'error': f'worker failed: {type(exc).__name__}: {str(exc)[:500]}'}
    finally:
        if read is not None:
            read.close()
        if write is not None:
            write.close()
        if process is not None:
            if started:
                process.join(0.1)
                if process.is_alive():
                    process.terminate()
                    process.join(0.5)
                if process.is_alive():
                    process.kill()
                    process.join()
            process.close()


class Runtime(EffectsMixin):
    """Trusted host API. Untrusted agents use AgentSession, not this class."""

    def __init__(self, path, registry, *, clock=time.time):
        self.store = Store(path)
        self.registry = registry
        self.clock = clock
        self.fault_hook = None
        self._operations = {}

    @contextmanager
    def _tx(self, run_id):
        try:
            with self.store.transaction() as tx:
                yield tx
        except AdmissionError as exc:
            # The rejected transaction has rolled back. Retain the denial separately.
            with self.store.transaction() as tx:
                tx.event(run_id, 'runtime_error', reason=str(exc), action='admission_denied')
            raise

    def create_run(self, state, gate_documents, *, bindings=None, actors=None,
                   writable_paths=None, max_attempts=3, max_seconds=10,
                   max_commits=1, admissibility_ref=None, allowed_operations=None,
                   effect_gate_documents=None, effect_bindings=None, source_identity=None):
        if type(state) is not dict or not gate_documents:
            raise ValueError('state object and required gate documents are mandatory')
        if not isinstance(gate_documents, list):
            raise ValueError('gate_documents must be a list')
        binding_list = bindings if bindings is not None else [None] * len(gate_documents)
        if len(binding_list) != len(gate_documents):
            raise ValueError('one binding entry is required per gate document')
        sets = [GateSet(d, b) for d, b in zip(gate_documents, binding_list)]
        effect_docs = effect_gate_documents or []
        effect_binding_list = effect_bindings if effect_bindings is not None else [None] * len(effect_docs)
        if len(effect_binding_list) != len(effect_docs):
            raise ValueError('invalid effect gate bindings')
        effect_sets = [GateSet(d, b) for d, b in zip(effect_docs, effect_binding_list)]
        operations = allowed_operations or []
        if operations and not effect_sets:
            raise ValueError('effect operations require separate pre-effect gate documents')
        if any(name not in self._operations for name in operations):
            raise ValueError('all operation adapters must be registered before freezing policy')
        # File/gate IDs are jointly scoped and cannot alias within a run.
        identities = []
        for gs in sets:
            doc = gs.document
            fid = doc.get('file_id') or doc.get('gate_id')
            for gate in doc.get('gates', [doc]):
                identities.append((fid, gate.get('gate_id')))
        if len(identities) != len(set(identities)):
            raise ValueError('duplicate file/gate identity')
        actors = actors or ['agent']
        if not isinstance(actors, list) or not all(isinstance(a, str) and a for a in actors):
            raise ValueError('actors must be named explicitly')
        paths = writable_paths or []
        if not paths:
            raise ValueError('writable_paths must be explicit')
        for path in paths:
            _pointer_parts(path)
        if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 60:
            raise ValueError('max_seconds must be finite and in (0,60]')
        policy = clone({
            'profile': 'mg8-runtime/0.1', 'actors': actors, 'writable_paths': paths,
            'gates': [{'document': gs.document, 'bindings': gs.bindings} for gs in sets],
            'max_attempts': _positive(max_attempts, 'max_attempts'),
            'max_commits': _positive(max_commits, 'max_commits'), 'max_seconds': max_seconds,
            'admissibility_ref': admissibility_ref,
            'allowed_operations': operations,
            'operation_versions': {name: self._operations[name]['digest'] for name in operations},
            'effect_gates': [{'document': g.document, 'bindings': g.bindings} for g in effect_sets],
            'source_identity': clone(source_identity),
        })
        run_id = _identifier('RUN')
        run = {'id': run_id, 'state': clone(state), 'version': 0, 'epoch': 0,
               'status': 'OPEN', 'attempts': 0, 'policy': policy,
               'policy_digest': digest(policy), 'registry': self.registry.fingerprint()}
        with self.store.transaction() as tx:
            tx.put('run', run_id, run)
            tx.event(run_id, 'external_input', action='run_created',
                     evidence={'state_digest': digest(state), 'policy_digest': run['policy_digest'],
                               'source_identity': policy['source_identity']})
        return run_id

    def snapshot(self, run_id):
        run = self.store.read('run', run_id)
        return {k: run[k] for k in ('id', 'state', 'version', 'epoch', 'status', 'attempts', 'policy_digest')}

    def _active(self, run):
        if run['status'] != 'OPEN':
            raise AdmissionError('run is not open: ' + run['status'])
        if self.registry.fingerprint() != run['registry']:
            raise AdmissionError('evaluator registry changed; policy revision required')

    def propose(self, run_id, actor, candidate, *, base_version, operation=None):
        candidate = clone(candidate)
        if type(candidate) is not dict:
            raise AdmissionError('candidate must be a state object')
        with self._tx(run_id) as tx:
            run = tx.get('run', run_id)
            self._active(run)
            if actor not in run['policy']['actors']:
                raise AdmissionError('actor not authorized')
            if type(base_version) is not int or base_version != run['version']:
                raise AdmissionError('stale base state')
            allowed = [_pointer_parts(p) for p in run['policy']['writable_paths']]
            if any(not any(path[:len(root)] == root for root in allowed)
                   for path in _changed(run['state'], candidate)):
                raise AdmissionError('candidate changes a protected state path')
            if operation is not None:
                operation = clone(operation)
                if set(operation) != {'name', 'arguments'} or type(operation['arguments']) is not dict:
                    raise AdmissionError('invalid operation proposal')
                if operation['name'] not in run['policy']['allowed_operations']:
                    raise AdmissionError('operation not allowed by policy')
            proposal_id = _identifier('PROPOSAL')
            proposal = {'id': proposal_id, 'run_id': run_id, 'actor': actor,
                        'base_version': base_version, 'epoch': run['epoch'],
                        'candidate': candidate, 'candidate_digest': digest(candidate),
                        'operation': operation, 'status': 'PROPOSED', 'evaluation': None}
            tx.put('proposal', proposal_id, proposal)
            tx.event(run_id, 'external_input', actor={'type': 'agent', 'id': actor},
                     action='proposal_received', evidence={'proposal_id': proposal_id,
                     'candidate_digest': proposal['candidate_digest']})
        return proposal_id

    def _proposal_current(self, run, proposal):
        self._active(run)
        if proposal['base_version'] != run['version'] or proposal['epoch'] != run['epoch']:
            raise AdmissionError('proposal state or policy version is stale')
        if proposal['status'] == 'COMMITTED':
            raise AdmissionError('proposal already committed')

    def record_evidence(self, proposal_id, key, value, *, kind, expires_at=None):
        """Trusted collector API, never expose directly to agent messages."""
        if not isinstance(key, str) or not key or '/' in key or '~' in key:
            raise ValueError('evidence key must be a simple nonempty name')
        if kind not in ('runtime', 'tool', 'human', 'model'):
            raise ValueError('unknown provenance kind')
        if expires_at is not None and (type(expires_at) not in (int, float) or not math.isfinite(expires_at)):
            raise ValueError('invalid expiry')
        value = clone(value)
        p = self.store.read('proposal', proposal_id)
        with self._tx(p['run_id']) as tx:
            run = tx.get('run', p['run_id'])
            p = tx.get('proposal', proposal_id)
            self._proposal_current(run, p)
            receipt = {'id': proposal_id + ':' + key, 'proposal_id': proposal_id,
                       'run_id': run['id'], 'key': key, 'value': value, 'kind': kind,
                       'candidate_digest': p['candidate_digest'], 'expires_at': expires_at,
                       'recorded_at': self.clock()}
            tx.put('receipt', receipt['id'], receipt)
            tx.event(run['id'], 'external_input', action='evidence_collected',
                     evidence=receipt)
        return receipt['id']

    def _receipts(self, tx, proposal):
        return sorted((r for r in tx.all('receipt') if r['proposal_id'] == proposal['id']), key=lambda r: r['key'])

    def _context(self, run, proposal, receipts):
        context = {'current': run['state'], 'candidate': proposal['candidate'],
                   'operation': proposal['operation'], 'evidence': {}, '_provenance': {}}
        def provenance(path, value, kind):
            context['_provenance'][path] = kind
            if type(value) is dict:
                for key, item in value.items():
                    provenance(path + '/' + key.replace('~', '~0').replace('/', '~1'), item, kind)
            if type(value) is list:
                for i, item in enumerate(value):
                    provenance(path + '/' + str(i), item, kind)
        for receipt in receipts:
            if receipt['candidate_digest'] != proposal['candidate_digest']:
                continue
            if receipt['expires_at'] is not None and receipt['expires_at'] <= self.clock():
                continue
            context['evidence'][receipt['key']] = receipt['value']
            provenance('/evidence/' + receipt['key'], receipt['value'], receipt['kind'])
        return clone(context)

    def evaluate(self, proposal_id, *, phase='commit'):
        if phase not in ('commit', 'effect'):
            raise ValueError('unknown evaluation phase')
        proposal = self.store.read('proposal', proposal_id)
        run_id = proposal['run_id']
        exhausted = False
        token, evidence_digest, context = '', '', {}
        with self._tx(run_id) as tx:
            run = tx.get('run', run_id)
            proposal = tx.get('proposal', proposal_id)
            self._proposal_current(run, proposal)
            if phase == 'effect' and (not proposal['operation'] or not run['policy']['effect_gates']):
                raise AdmissionError('no declared effect phase')
            if proposal['status'] == 'EVALUATING':
                raise AdmissionError('proposal already being evaluated')
            if run['attempts'] >= run['policy']['max_attempts']:
                run['status'] = 'UNRESOLVED'
                tx.put('run', run_id, run)
                tx.event(run_id, 'runtime_error', action='bound_exhausted', reason='UNRESOLVED')
                exhausted = True
            else:
                run['attempts'] += 1
                tx.put('run', run_id, run)
                proposal['status'] = 'EVALUATING'
                token = _identifier('EVAL')
                proposal['token'] = token
                tx.put('proposal', proposal_id, proposal)
                receipts = self._receipts(tx, proposal)
                evidence_digest = digest(receipts)
                context = self._context(run, proposal, receipts)
                tx.event(run_id, 'external_input', action='evaluation_started',
                         evidence={'proposal_id': proposal_id, 'attempt': run['attempts']})
        if exhausted:
            raise AdmissionError('loop bound exhausted: UNRESOLVED')

        def compute():
            admissibility = None
            if run['policy']['admissibility_ref']:
                result = self.registry.evaluate({'evaluator_ref': run['policy']['admissibility_ref'],
                                                 'requirement': 'declared trajectory admissibility'}, context)
                result_name = result.outcome.value
                mapped = 'INTERMEDIATE' if result_name == 'UNKNOWN' else result_name
                admissibility = {'result': mapped, 'reason': result.reason, 'evidence': result.evidence}
                if mapped != 'PASS':
                    return {'outcome': mapped, 'gates': [], 'admissibility': admissibility}
            gate_key = 'gates' if phase == 'commit' else 'effect_gates'
            reports = [GateSet(g['document'], g['bindings']).evaluate(context, self.registry)
                       for g in run['policy'][gate_key]]
            all_gates = [g for r in reports for g in r['gates']]
            results = [r['outcome'] for r in reports]
            overall = 'FAIL' if 'FAIL' in results else ('PASS' if all(r == 'PASS' for r in results) else 'INTERMEDIATE')
            return {'outcome': overall, 'gates': all_gates, 'admissibility': admissibility}

        worker_result = isolated(compute, run['policy']['max_seconds'])
        report = worker_result.get('value')
        if not isinstance(report, dict):
            report = {'outcome': 'INTERMEDIATE', 'gates': [], 'error': worker_result.get('error', 'invalid evaluation')}
        with self._tx(run_id) as tx:
            current_run = tx.get('run', run_id)
            current_p = tx.get('proposal', proposal_id)
            try:
                self._proposal_current(current_run, current_p)
                if current_p.get('token') != token or digest(self._receipts(tx, current_p)) != evidence_digest:
                    raise AdmissionError('proposal or evidence changed during evaluation')
            except AdmissionError:
                tx.event(run_id, 'runtime_error', action='late_evaluation_discarded',
                         reason='state/policy/evidence/cancellation changed', evidence={'proposal_id': proposal_id})
                current_p['status'] = 'STALE'
                tx.put('proposal', proposal_id, current_p)
                return {'outcome': 'INTERMEDIATE', 'gates': [], 'error': 'late evaluation discarded'}
            for gate in report['gates']:
                tx.event(run_id, 'gate_attempt', file_id=gate['file_id'], gate_id=gate['gate_id'],
                         input_state_id=f'{run_id}:{run["version"]}', result=gate['result'],
                         action=gate['route'], evidence={'proposal_id': proposal_id,
                         'candidate_digest': proposal['candidate_digest'], 'evaluation': gate})
            if report.get('error'):
                tx.event(run_id, 'runtime_error', reason=report['error'], action='evaluation_unresolved')
            if report.get('admissibility'):
                tx.event(run_id, 'review', action='admissibility_evaluated', evidence=report['admissibility'])
            current_p['status'] = 'EVALUATED'
            current_p['evaluation'] = {'report': report, 'evidence_digest': evidence_digest,
                                       'registry': self.registry.fingerprint(), 'policy_digest': run['policy_digest'],
                                       'candidate_digest': proposal['candidate_digest'], 'phase': phase}
            tx.put('proposal', proposal_id, current_p)
        return clone(report)

    def _validated(self, tx, run, proposal):
        self._proposal_current(run, proposal)
        evaluation = proposal['evaluation']
        if proposal['status'] != 'EVALUATED' or not evaluation or evaluation['report']['outcome'] != 'PASS':
            raise AdmissionError('proposal has no passing runtime evaluation')
        if evaluation['registry'] != self.registry.fingerprint() or evaluation['policy_digest'] != run['policy_digest']:
            raise AdmissionError('evaluation policy or implementation changed')
        if evaluation['candidate_digest'] != digest(proposal['candidate']):
            raise AdmissionError('candidate changed')
        receipts = self._receipts(tx, proposal)
        if digest(receipts) != evaluation['evidence_digest']:
            raise AdmissionError('evidence changed since evaluation')
        if any(r['expires_at'] is not None and r['expires_at'] <= self.clock() for r in receipts):
            raise AdmissionError('evidence expired')
        gates = evaluation['report']['gates']
        if not gates or any(g['result'] != 'PASS' or g['route'] not in ('continue', 'commit') for g in gates) or gates[-1]['route'] != 'commit':
            raise AdmissionError('declared gate routes do not authorize commit')

    def authorize(self, proposal_id, *, ttl=60, purpose='commit'):
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 < ttl <= 3600:
            raise ValueError('invalid permit ttl')
        if purpose not in ('commit', 'effect'):
            raise ValueError('unknown permit purpose')
        p = self.store.read('proposal', proposal_id)
        with self._tx(p['run_id']) as tx:
            p = tx.get('proposal', proposal_id)
            run = tx.get('run', p['run_id'])
            self._validated(tx, run, p)
            if p['evaluation']['phase'] != purpose:
                raise AdmissionError('evaluation phase does not authorize this permit purpose')
            if purpose == 'effect' and p['operation'] is None:
                raise AdmissionError('effect permit requires an operation proposal')
            permit_id = _identifier('PERMIT')
            permit = {'id': permit_id, 'run_id': run['id'], 'proposal_id': proposal_id,
                      'status': 'ISSUED', 'purpose': purpose, 'expires_at': self.clock() + ttl,
                      'version': run['version'], 'epoch': run['epoch'],
                      'evaluation_digest': digest(p['evaluation']), 'actor': p['actor'],
                      'operation': p['operation']}
            tx.put('permit', permit_id, permit)
            tx.event(run['id'], 'review', action='permit_issued', evidence=permit)
        return permit_id

    def _permit(self, tx, permit_id, purpose):
        permit = tx.get('permit', permit_id)
        run = tx.get('run', permit['run_id'])
        p = tx.get('proposal', permit['proposal_id'])
        if permit['status'] != 'ISSUED' or permit['expires_at'] <= self.clock():
            raise AdmissionError('permit consumed, revoked or expired')
        if permit['purpose'] != purpose:
            raise AdmissionError('permit purpose mismatch')
        if permit['epoch'] != run['epoch'] or permit['version'] != run['version']:
            raise AdmissionError('permit version mismatch')
        self._validated(tx, run, p)
        if permit['evaluation_digest'] != digest(p['evaluation']):
            raise AdmissionError('permit evaluation superseded')
        return permit, run, p

    def commit(self, permit_id):
        initial = self.store.read('permit', permit_id)
        with self._tx(initial['run_id']) as tx:
            permit, run, p = self._permit(tx, permit_id, 'commit')
            if p['operation'] is not None:
                try:
                    operation = tx.get('operation', 'OP_' + p['id'])
                except KeyError:
                    raise AdmissionError('proposed effect has not completed') from None
                if operation['status'] != 'SUCCEEDED':
                    raise AdmissionError('proposed effect has an unresolved or failed outcome')
            old_version = run['version']
            run['state'] = p['candidate']
            run['version'] += 1
            run['attempts'] = 0
            if run['version'] >= run['policy']['max_commits']:
                run['status'] = 'COMPLETE'
            tx.put('run', run['id'], run)
            if self.fault_hook:
                self.fault_hook('after_state_write')
            permit['status'] = 'CONSUMED'
            p['status'] = 'COMMITTED'
            tx.put('permit', permit_id, permit)
            tx.put('proposal', p['id'], p)
            tx.event(run['id'], 'state_commit', input_state_id=f'{run["id"]}:{old_version}',
                     output_state_id=f'{run["id"]}:{run["version"]}', action='commit',
                     evidence={'permit_id': permit_id, 'proposal_id': p['id'],
                               'candidate_digest': p['candidate_digest']})
        return self.snapshot(initial['run_id'])

    def revoke(self, permit_id, reason):
        initial = self.store.read('permit', permit_id)
        with self._tx(initial['run_id']) as tx:
            permit = tx.get('permit', permit_id)
            if permit['status'] != 'ISSUED':
                raise AdmissionError('only an issued permit may be revoked')
            permit['status'] = 'REVOKED'
            tx.put('permit', permit_id, permit)
            tx.event(permit['run_id'], 'review', action='permit_revoked', reason=str(reason), evidence={'permit_id': permit_id})

    def cancel(self, run_id):
        with self._tx(run_id) as tx:
            run = tx.get('run', run_id)
            run['status'] = 'CANCELLED'
            run['epoch'] += 1
            tx.put('run', run_id, run)
            tx.event(run_id, 'review', action='run_cancelled')

    def resume(self, run_id, *, reason):
        """Trusted review continuation; never reset bounds or revive prior permits."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('review continuation requires a reason')
        with self._tx(run_id) as tx:
            run = tx.get('run', run_id)
            if run['status'] != 'REVIEW':
                raise AdmissionError('only a reviewed run may be resumed')
            for permit in tx.all('permit'):
                if permit['run_id'] == run_id and permit['status'] == 'ISSUED':
                    permit['status'] = 'REVOKED'
                    tx.put('permit', permit['id'], permit)
                    tx.event(run_id, 'review', action='permit_revoked_on_resume', evidence={'permit_id': permit['id']})
            run['status'] = 'OPEN'
            tx.put('run', run_id, run)
            tx.event(run_id, 'review', action='review_resumed', reason=reason)

    def revise_policy(self, run_id, gate_documents, *, bindings=None, source_identity=None):
        binding_list = bindings if bindings is not None else [None] * len(gate_documents)
        if not gate_documents or len(binding_list) != len(gate_documents):
            raise ValueError('invalid gate/binding set')
        sets = [GateSet(d, b) for d, b in zip(gate_documents, binding_list)]
        with self._tx(run_id) as tx:
            run = tx.get('run', run_id)
            if run['status'] != 'OPEN':
                raise AdmissionError('cannot revise a closed run')
            run['policy']['gates'] = [{'document': g.document, 'bindings': g.bindings} for g in sets]
            run['policy']['source_identity'] = clone(source_identity)
            run['policy_digest'] = digest(run['policy'])
            run['registry'] = self.registry.fingerprint()
            run['epoch'] += 1
            tx.put('run', run_id, run)
            tx.event(run_id, 'review', action='policy_revision', evidence={'epoch': run['epoch'], 'policy_digest': run['policy_digest']})


class AgentSession:
    """Narrow in-process facade; use a process boundary for hostile agent code."""
    def __init__(self, runtime, run_id, actor):
        self.__runtime, self.__run_id, self.__actor = runtime, run_id, actor

    def snapshot(self):
        return self.__runtime.snapshot(self.__run_id)

    def propose(self, candidate, *, base_version, operation=None):
        return self.__runtime.propose(self.__run_id, self.__actor, candidate,
                                      base_version=base_version, operation=operation)
