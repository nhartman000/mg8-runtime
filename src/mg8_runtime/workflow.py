"""Bounded sequential proposal/TEST/revise/TEST/commit workflow profile."""
from .canonical import clone
from .runtime import AdmissionError, isolated


def _finish(runtime, run_id, status, reason):
    with runtime._tx(run_id) as tx:
        run = tx.get('run', run_id)
        if run['status'] == 'OPEN':
            run['status'] = status
            tx.put('run', run_id, run)
            tx.event(run_id, 'review', action='workflow_' + status.lower(), reason=reason)
        return {'run_id': run_id, 'status': run['status'], 'reason': reason}


def run_workflow(runtime, run_id, actor, proposer):
    """Run a trusted transport callback returning only candidate/operation proposals.

    The callback receives detached snapshot and previous evaluation. It cannot
    create trusted receipts through the returned proposal envelope. Real remote
    effects use Runtime's separate pre-effect/dispatch/postcondition API.
    """
    previous = None
    while True:
        snapshot = runtime.snapshot(run_id)
        if snapshot['status'] != 'OPEN':
            return {'run_id': run_id, 'status': snapshot['status']}
        policy = runtime.store.read('run', run_id)['policy']
        if snapshot['attempts'] >= policy['max_attempts']:
            return _finish(runtime, run_id, 'UNRESOLVED', 'iteration bound exhausted without verified EXIT')
        response = isolated(lambda: proposer(clone(snapshot), clone(previous)), policy['max_seconds'])
        envelope = response.get('value')
        if not isinstance(envelope, dict) or 'candidate' not in envelope or set(envelope) - {'candidate', 'operation'}:
            return _finish(runtime, run_id, 'REJECTED', response.get('error', 'invalid agent proposal envelope'))
        try:
            proposal_id = runtime.propose(run_id, actor, envelope['candidate'],
                base_version=snapshot['version'], operation=envelope.get('operation'))
            if envelope.get('operation') is not None:
                return _finish(runtime, run_id, 'REVIEW', 'effect proposal requires explicit host pre-effect authorization and dispatch')
            report = runtime.evaluate(proposal_id)
            previous = report
            if report['outcome'] == 'PASS':
                state = runtime.commit(runtime.authorize(proposal_id))
                if state['status'] == 'COMPLETE':
                    return {'run_id': run_id, 'status': 'COMPLETE', 'state': state['state'], 'version': state['version']}
                previous = None
                continue
            blocking = [g for g in report['gates'] if g['result'] != 'PASS']
            if blocking and all(g['route'] == 'repeat' for g in blocking):
                continue
            if any(g['route'] in ('stop', 'reject') for g in blocking) or report['outcome'] == 'FAIL':
                return _finish(runtime, run_id, 'REJECTED', 'declared gate routing rejected proposal')
            return _finish(runtime, run_id, 'REVIEW', report.get('error', 'unresolved requirement or declared review route'))
        except AdmissionError as exc:
            return _finish(runtime, run_id, 'REVIEW', str(exc))
