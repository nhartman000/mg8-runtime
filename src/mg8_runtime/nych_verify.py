"""Independent read-only verifier for the narrow NYCH one-unit demonstration.

Reads actual files and SQLite directly; does not import the producer, instantiate
Runtime/Store, or accept a producer success flag. Hashes are integrity checks,
not signatures or proof against a malicious host rewriting the entire bundle.
Shares GateSet/Registry, loader and digest semantics: independent persisted-state
verification, not an independently reimplemented gate engine.
"""
from contextlib import closing
from datetime import datetime
import math
import hashlib
import json
import sqlite3
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker

from .canonical import digest
from .loader import load_unit
from .gates import GateSet, Registry, Evaluation, Outcome


def check_gate(event, document, context):
    # Independent mechanical replay; do not import the producer's adapter.
    def replay(ctx, condition):
        arguments = ctx['operation']['arguments']
        raw = ('UNKNOWN' if 'text' not in arguments else
               'PASS' if arguments['text'] == ctx['current']['nych']['encoded'] + '\n' else 'FAIL')
        reason = 'no_evaluator_attached' if raw == 'UNKNOWN' else 'NYCH checkpoint text comparison'
        return Evaluation(Outcome(raw), reason, {'implementation': 'nych.gates.AtomicRequirement', 'raw_outcome': raw})
    registry = Registry()
    registry.register('nych.operation-text@1', replay, kind='mechanical', version='1')
    report = GateSet(document).evaluate(context, registry)['gates'][0]
    require(event['evidence']['evaluation'] == report, 'gate evaluation does not independently replay')
    require(event['file_id'] == report['file_id'] and event['gate_id'] == report['gate_id']
            and event['result'] == report['result'] and event['action'] == report['route'], 'gate identity/result mismatch')


def require(value, message):
    if not value:
        raise ValueError(message)


def schema(name):
    return json.loads(files('mg8_runtime').joinpath('schemas', name).read_text(encoding='utf-8'))


def verify(directory):
    import nych
    from importlib.metadata import version
    from nych.semantic_encoding import encode_text, audit_summary
    root = Path(directory).resolve(strict=True)
    require(not any(p.is_symlink() for p in root.iterdir()), 'symlink evidence unsupported')
    read = lambda name: json.loads((root / name).read_text(encoding='utf-8'))
    source = (root / 'source.txt').read_text(encoding='utf-8')
    require(source == 'I see a red light.', 'unexpected task source')
    encoded, records = encode_text(source)
    checkpoint = {'original': source, 'encoded': encoded, 'records': records, 'audit': audit_summary(records)}
    require(read('encoded.json') == checkpoint, 'NYCH checkpoint does not re-encode')
    payload = (encoded + '\n').encode('utf-8')
    sha = hashlib.sha256(payload).hexdigest()
    unit = load_unit(root / 'unit.mg8')
    require(unit.initial_state == {'nych': checkpoint, 'artifact': None}, 'initial GST mismatch')
    qson = read('execution.qson')
    Draft7Validator(schema('qson.schema.json'), format_checker=FormatChecker()).validate(qson)
    for name in ('commit.g8son', 'effect.g8son'):
        Draft7Validator(schema('g8son.schema.json')).validate(read(name))
    run_id = qson['run_id']
    events = qson['events']
    previous, traces = None, set()
    for sequence, event in enumerate(events, 1):
        require(event['sequence'] == sequence and event['run_id'] == run_id, 'sequence/run mismatch')
        require(event['trace_id'] not in traces, 'duplicate trace')
        traces.add(event['trace_id'])
        require(event.get('previous_event_hash') == previous, 'broken QSON chain')
        unsigned = dict(event)
        previous = unsigned.pop('event_hash')
        require(previous == digest(unsigned), 'invalid QSON event hash')
    # Completed, checkpointed bundles only; immutable avoids even WAL/SHM writes.
    with closing(sqlite3.connect((root / 'runtime.sqlite').as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        rows = db.execute('SELECT kind,id,record FROM records').fetchall()
        persisted = [json.loads(row[0]) for row in db.execute(
            'SELECT event FROM events ORDER BY run_id,sequence')]
    require(persisted == events, 'export differs from persisted QSON or contains other runs')
    records_by_kind = {}
    for kind, key, raw in rows:
        records_by_kind.setdefault(kind, {})[key] = json.loads(raw)
    require(set(records_by_kind) <= {'run', 'proposal', 'permit', 'operation', 'receipt'}, 'unsupported record kind')
    for kind, entries in records_by_kind.items():
        require(all(record['id'] == key for key, record in entries.items()), 'record key/identity mismatch')
    require(set(records_by_kind['run']) == {run_id}, 'unexpected runs')
    run = records_by_kind['run'][run_id]
    policy = run['policy']
    require(run['policy_digest'] == digest(policy), 'policy hash mismatch')
    identity = policy['source_identity']
    require(identity['integration_profile'] == 'nych-runtime-one-unit/1', 'wrong host profile')
    require(events[0]['action'] == 'run_created'
            and events[0]['evidence'] == {'state_digest': digest(unit.initial_state),
                'policy_digest': run['policy_digest'], 'source_identity': identity}, 'initial ledger/source/policy binding mismatch')
    expected_implementation = {
        'nych/' + name: hashlib.sha256((Path(nych.__file__).parent / name).read_bytes()).hexdigest()
        for name in ('gates.py', 'semantic_encoding.py', 'semantic_registry.py', 'data/sense_registry.json')}
    require(identity['implementation_sha256'] == expected_implementation, 'NYCH implementation changed')
    require(identity['distributions'] == {name: version(name) for name in ('nych', 'mg8-runtime')}, 'distribution version mismatch')
    require(identity['unit_id'] == unit.manifest['unit_id'] == 'nych.bounded-encoding', 'wrong unit')
    expected_sources = dict(unit.sources)
    for name in ('effect.g8son', 'source.txt', 'encoded.json'):
        expected_sources[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    require(identity['resources'] == expected_sources, 'source bindings changed')
    require(policy['gates'] == [{'document': unit.gate_documents[0], 'bindings': unit.bindings[0]}], 'commit gate binding mismatch')
    require(policy['effect_gates'] == [{'document': read('effect.g8son'), 'bindings': {}}], 'effect gate binding mismatch')
    for key in ('actors', 'writable_paths', 'max_attempts', 'max_seconds', 'max_commits'):
        require(policy[key] == unit.policy[key], 'unit policy mismatch: ' + key)
    require(policy['allowed_operations'] == ['demo.write-encoded@1'], 'operation allowlist mismatch')
    expected_candidate = {'nych': checkpoint, 'artifact': {'path': 'accepted.txt', 'sha256': sha}}
    proposals = list(records_by_kind.get('proposal', {}).values())
    require(len(proposals) == 1, 'expected one bounded proposal')
    proposal = proposals[0]
    pid = proposal['id']
    candidate_hash = digest(expected_candidate)
    require(proposal['candidate'] == expected_candidate and proposal['candidate_digest'] == candidate_hash, 'candidate mismatch')
    require(proposal['run_id'] == run_id and proposal['base_version'] == 0, 'proposal binding mismatch')
    expected_operation = {'name': 'demo.write-encoded@1', 'arguments': {'path': 'accepted.txt', 'text': payload.decode()}}
    attempts = [e for e in events if e['event_type'] == 'gate_attempt']
    context = {'current': unit.initial_state, 'candidate': proposal['candidate'],
               'operation': proposal['operation'], 'evidence': {}, '_provenance': {}}
    require(bool(attempts), 'missing admission attempt')
    blocked = attempts[0]['result'] != 'PASS'
    expected_transitions = [
        ('external_input', 'run_created'), ('external_input', 'proposal_received'),
        ('external_input', 'evaluation_started'), ('gate_attempt', attempts[0]['action'])]
    expected_transitions += ([('runtime_error', 'admission_denied')] * 2 if blocked else [
        ('review', 'permit_issued'), ('external_input', 'effect_dispatch_prepared'),
        ('external_input', 'effect_receipt'), ('external_input', 'evidence_collected'),
        ('external_input', 'evaluation_started'), ('gate_attempt', 'commit'),
        ('review', 'permit_issued'), ('state_commit', 'commit')])
    require([(e['event_type'], e.get('action')) for e in events] == expected_transitions,
            'unsupported audited transition inventory/order')
    require(run['epoch'] == proposal['epoch'] == 0 and proposal['actor'] == 'offline-host', 'epoch/actor mismatch')
    require(run['attempts'] == (1 if blocked else 0), 'attempt count mismatch')
    require(events[1]['evidence'] == {'proposal_id': pid, 'candidate_digest': candidate_hash}, 'proposal audit mismatch')
    starts = [e for e in events if e.get('action') == 'evaluation_started']
    for number, event in enumerate(starts, 1):
        require(event['evidence'] == {'proposal_id': pid, 'attempt': number}, 'evaluation start mismatch')
    for event in attempts:
        require(event['evidence']['proposal_id'] == pid and event['evidence']['candidate_digest'] == candidate_hash,
                'gate candidate binding mismatch')
    check_gate(attempts[0], read('effect.g8son'), context)
    if attempts[0]['result'] != 'PASS':
        denied_operation = {'name': 'demo.write-encoded@1', 'arguments': {'path': 'accepted.txt', 'text': payload.decode() + 'denied'}}
        unknown_operation = {'name': 'demo.write-encoded@1', 'arguments': {'path': 'accepted.txt'}}
        require(proposal['operation'] in (denied_operation, unknown_operation), 'unknown blocked scenario')
        expected_outcome = 'FAIL' if proposal['operation'] == denied_operation else 'INTERMEDIATE'
        require(len(attempts) == 1 and attempts[0]['gate_id'] == 'exact-operation-admission'
                and attempts[0]['result'] == expected_outcome, 'blocked gate evidence mismatch')
        require(not (root / 'accepted.txt').exists(), 'blocked run wrote accepted artifact')
        require(run['status'] == 'OPEN' and proposal['status'] == 'EVALUATED', 'blocked lifecycle mismatch')
        require(run['version'] == 0 and run['state'] == unit.initial_state, 'blocked run committed state')
        require(read('committed.gst') == {'gst_version': '1.0', 'state': unit.initial_state}, 'blocked GST mismatch')
        require(set(records_by_kind) == {'run', 'proposal'}, 'blocked record inventory mismatch')
        evaluation = {'report': {'outcome': expected_outcome, 'gates': [attempts[0]['evidence']['evaluation']], 'admissibility': None},
                      'evidence_digest': digest([]), 'registry': run['registry'], 'policy_digest': run['policy_digest'],
                      'candidate_digest': candidate_hash, 'phase': 'effect'}
        require(proposal['evaluation'] == evaluation, 'blocked proposal evaluation mismatch')
        require(not records_by_kind.get('permit') and not records_by_kind.get('operation'), 'blocked run obtained authority')
        require(not any(e['event_type'] == 'state_commit' or e.get('action') == 'effect_dispatch_prepared' for e in events), 'blocked ledger has effects/commit')
        require(sum(e.get('action') == 'admission_denied' for e in events) == 2, 'denial evidence missing')
        return {'status': 'VERIFIED_BLOCKED', 'run_id': run_id, 'outcome': attempts[0]['result']}
    require(proposal['status'] == 'COMMITTED', 'successful proposal not committed')
    require(proposal['operation'] == expected_operation, 'exact operation mismatch')
    require(run['state'] == expected_candidate and run['version'] == 1 and run['status'] == 'COMPLETE', 'final runtime state not complete')
    require(read('committed.gst') == {'gst_version': '1.0', 'state': expected_candidate}, 'GST snapshot mismatch')
    require((root / 'accepted.txt').read_bytes() == payload, 'external final-state mismatch')
    require(set(records_by_kind.get('operation', {})) == {'OP_' + pid}, 'expected exactly one supported operation')
    require(set(records_by_kind.get('receipt', {})) == {pid + ':operation', pid + ':observation'}, 'unexpected receipt inventory')
    operation = records_by_kind['operation']['OP_' + pid]
    require(read('operation.json') == operation, 'operation snapshot mismatch')
    require(operation['status'] == 'SUCCEEDED' and operation['operation'] == proposal['operation']
            and operation['candidate_digest'] == candidate_hash, 'operation receipt mismatch')
    require(operation['adapter_digest'] == policy['operation_versions']['demo.write-encoded@1'], 'adapter binding mismatch')
    require(operation['result'] == {'path': 'accepted.txt', 'sha256': sha, 'operation_id': operation['id']}, 'adapter return mismatch')
    prepared = {key: value for key, value in operation.items() if key not in ('reason', 'result')}
    prepared['status'] = 'IN_FLIGHT'
    require(events[5]['evidence'] == prepared, 'dispatch preparation differs from operation lifecycle')
    operation_receipt = records_by_kind['receipt'][pid + ':operation']
    require(operation_receipt['key'] == 'operation' and operation_receipt['kind'] == 'tool'
            and operation_receipt['value'] == {'operation_id': operation['id'], 'status': 'SUCCEEDED', 'result': operation['result']},
            'operation receipt differs from audited result')
    observation = records_by_kind['receipt'][pid + ':observation']
    require(observation['value'] == {'path': 'accepted.txt', 'sha256': sha}
            and observation['kind'] == 'tool' and observation['candidate_digest'] == candidate_hash, 'fresh observation receipt mismatch')
    for receipt in records_by_kind['receipt'].values():
        require(receipt['proposal_id'] == pid and receipt['run_id'] == run_id
                and receipt['candidate_digest'] == candidate_hash, 'receipt binding mismatch')
        key = receipt['key']
        context['evidence'][key] = receipt['value']
        def provenance(path, value):
            context['_provenance'][path] = receipt['kind']
            if isinstance(value, dict):
                for field, item in value.items():
                    provenance(path + '/' + field, item)
        provenance('/evidence/' + key, receipt['value'])
    require(len(attempts) == 2, 'expected admission and postcondition attempts')
    check_gate(attempts[1], read('commit.g8son'), context)
    commits = [e for e in events if e['event_type'] == 'state_commit']
    require(len(commits) == 1, 'expected exactly one commit')
    commit = commits[0]
    require(commit['evidence']['proposal_id'] == pid and commit['evidence']['candidate_digest'] == candidate_hash, 'commit binding mismatch')
    require(commit['input_state_id'] == run_id + ':0' and commit['output_state_id'] == run_id + ':1', 'commit version mismatch')
    attempts = [e for e in events if e['event_type'] == 'gate_attempt']
    require([(e['gate_id'], e['result']) for e in attempts] == [('exact-operation-admission', 'PASS'), ('fresh-final-state', 'PASS')], 'gate attempts mismatch')
    actions = {e.get('action'): e['sequence'] for e in events}
    require(attempts[0]['sequence'] < actions['effect_dispatch_prepared'] < actions['effect_receipt']
            < actions['evidence_collected'] < attempts[1]['sequence'] < commit['sequence'], 'admission/effect/observation/commit order')
    for event in attempts:
        require(event['evidence']['proposal_id'] == pid and event['evidence']['candidate_digest'] == candidate_hash, 'gate candidate binding mismatch')
    permits = list(records_by_kind['permit'].values())
    require(len(permits) == 2 and {p['purpose'] for p in permits} == {'effect', 'commit'}, 'permit lifecycle mismatch')
    require(all(p['status'] == 'CONSUMED' and p['proposal_id'] == pid and p['operation'] == proposal['operation'] for p in permits), 'unconsumed or wrong permit')
    commit_permit = next(p for p in permits if p['purpose'] == 'commit')
    require(commit['evidence']['permit_id'] == commit_permit['id'], 'commit did not consume commit authority')
    require(operation['id'] == 'OP_' + pid and operation['proposal_id'] == pid
            and operation['run_id'] == run_id, 'operation identity binding mismatch')
    require(next(e for e in events if e.get('action') == 'effect_receipt')['evidence'] == operation, 'audited operation differs from record')
    require(next(e for e in events if e.get('action') == 'evidence_collected')['evidence'] == observation, 'audited observation differs from record')
    receipt_list = sorted(records_by_kind['receipt'].values(), key=lambda r: r['key'])
    for permit in permits:
        phase = permit['purpose']
        evaluation = {'report': {'outcome': 'PASS', 'gates': [attempts[0 if phase == 'effect' else 1]['evidence']['evaluation']], 'admissibility': None},
                      'evidence_digest': digest([] if phase == 'effect' else receipt_list),
                      'registry': run['registry'], 'policy_digest': run['policy_digest'],
                      'candidate_digest': candidate_hash, 'phase': phase}
        require(permit['evaluation_digest'] == digest(evaluation), 'permit evaluation binding mismatch')
        require(permit['run_id'] == run_id and permit['version'] == 0 and permit['epoch'] == 0
                and permit['actor'] == proposal['actor'] and permit.get('candidate_digest', candidate_hash) == candidate_hash,
                'permit state/actor/candidate binding mismatch')
        issued = dict(permit, status='ISSUED')
        matching = [e for e in events if e.get('action') == 'permit_issued' and e['evidence'] == issued]
        require(len(matching) == 1, 'issued permit evidence missing')
        expiry = permit['expires_at']
        require(type(expiry) in (int, float) and math.isfinite(expiry), 'invalid permit expiry')
        consumed = events[actions['effect_dispatch_prepared'] - 1] if phase == 'effect' else commit
        issued_at = datetime.fromisoformat(matching[0]['timestamp'].replace('Z', '+00:00')).timestamp()
        consumed_at = datetime.fromisoformat(consumed['timestamp'].replace('Z', '+00:00')).timestamp()
        require(issued_at <= consumed_at < expiry, 'permit expired before audited consumption')
        require(attempts[0 if phase == 'effect' else 1]['sequence'] < matching[0]['sequence']
                < (actions['effect_dispatch_prepared'] if phase == 'effect' else commit['sequence']), 'permit order mismatch')
        if phase == 'commit':
            require(proposal['evaluation'] == evaluation, 'committed proposal evaluation mismatch')
    return {'status': 'VERIFIED_COMPLETE', 'run_id': run_id, 'events': len(events), 'artifact_sha256': sha}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.directory), sort_keys=True))
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f'verification error: {exc}\n')


if __name__ == '__main__':
    main()
