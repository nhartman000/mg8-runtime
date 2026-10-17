"""Durable pre-effect authorization and explicit uncertain-outcome reconciliation."""
import math
from typing import Any, Callable

from .canonical import clone
from .gates import Registry


def _adapter_digest(name, adapter, version):
    registry = Registry()
    registry.register(name, adapter, kind='operation', version=version)
    return registry.fingerprint()


class EffectsMixin:
    # Runtime supplies these host capabilities; annotations do not expose them to agents.
    _operations: dict
    store: Any
    clock: Callable
    fault_hook: Any
    _tx: Any
    _permit: Any

    def register_operation(self, name, adapter, *, version='1'):
        """Trusted host registration only; no arbitrary references from agent input."""
        if not isinstance(name, str) or not name or name in self._operations or not callable(adapter):
            raise ValueError('unique named callable adapter required')
        code = getattr(adapter, '__code__', None)
        if code is None:
            raise ValueError('operation adapters must be Python functions with inspectable code')
        self._operations[name] = {'call': adapter, 'version': version,
                                  'digest': _adapter_digest(name, adapter, version)}

    def dispatch(self, permit_id, *, timeout=None):
        """Consume before dispatch; an interrupted effect is UNKNOWN, never retried."""
        from .runtime import AdmissionError, isolated
        initial = self.store.read('permit', permit_id)
        with self._tx(initial['run_id']) as tx:
            permit, run, p = self._permit(tx, permit_id, 'effect')
            operation = p['operation']
            adapter = self._operations.get(operation['name'])
            if not adapter or run['policy']['operation_versions'].get(operation['name']) != _adapter_digest(operation['name'], adapter['call'], adapter['version']):
                raise AdmissionError('operation adapter missing or changed')
            seconds = run['policy']['max_seconds'] if timeout is None else timeout
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= run['policy']['max_seconds']:
                raise AdmissionError('invalid operation deadline')
            operation_id = 'OP_' + p['id']
            try:
                tx.get('operation', operation_id)
            except KeyError:
                pass
            else:
                raise AdmissionError('operation already dispatched; reconcile its existing record')
            record = {'id': operation_id, 'run_id': run['id'], 'proposal_id': p['id'],
                      'status': 'IN_FLIGHT', 'operation': operation,
                      'adapter_digest': adapter['digest'], 'candidate_digest': p['candidate_digest']}
            permit['status'] = 'CONSUMED'
            tx.put('permit', permit_id, permit)
            tx.put('operation', operation_id, record)
            tx.event(run['id'], 'external_input', action='effect_dispatch_prepared', evidence=record)
        if self.fault_hook:
            self.fault_hook('after_effect_dispatch_record')
        result = isolated(lambda: adapter['call'](clone(operation['arguments']), operation_id), seconds)
        status = 'SUCCEEDED' if 'value' in result else 'UNKNOWN'
        with self._tx(initial['run_id']) as tx:
            record = tx.get('operation', operation_id)
            if record['status'] != 'IN_FLIGHT':
                # Reconciliation is authoritative. A late transport return is not
                # independent postcondition evidence and cannot replace it.
                tx.event(initial['run_id'], 'review', action='late_effect_result_discarded',
                         reason='operation was already reconciled',
                         evidence={'operation_id': operation_id, 'retained_status': record['status'],
                                   'late_result': result})
                return clone(record)
            record['status'] = status
            record['result'] = result.get('value')
            record['reason'] = result.get('error', 'adapter returned; postcondition verification still required')
            tx.put('operation', operation_id, record)
            self._effect_receipt(tx, record)
        return clone(record)

    def _effect_receipt(self, tx, operation):
        receipt = {'id': operation['proposal_id'] + ':operation', 'proposal_id': operation['proposal_id'],
                   'run_id': operation['run_id'], 'key': 'operation',
                   'value': {'operation_id': operation['id'], 'status': operation['status'], 'result': operation.get('result')},
                   'kind': 'tool', 'candidate_digest': operation['candidate_digest'],
                   'expires_at': None, 'recorded_at': self.clock()}
        tx.put('receipt', receipt['id'], receipt)
        tx.event(operation['run_id'], 'external_input', action='effect_receipt', evidence=operation)

    def reconcile_operation(self, operation_id, *, status, result, reason):
        """Trusted host records independent resolution; never redispatches."""
        from .runtime import AdmissionError
        if status not in ('SUCCEEDED', 'FAILED', 'UNKNOWN') or not isinstance(reason, str) or not reason:
            raise ValueError('explicit resolution and reason required')
        result = clone(result)
        initial = self.store.read('operation', operation_id)
        with self._tx(initial['run_id']) as tx:
            record = tx.get('operation', operation_id)
            if record['status'] not in ('UNKNOWN', 'IN_FLIGHT'):
                raise AdmissionError('only uncertain operation outcomes may be reconciled')
            record.update(status=status, result=result, reason=reason)
            tx.put('operation', operation_id, record)
            tx.event(record['run_id'], 'correction', reason=reason,
                     references=[operation_id], action='effect_reconciliation', evidence=record)
            self._effect_receipt(tx, record)
