"""Offline, one-unit NYCH semantic-encoder / runtime host integration.

No inference, universal ORK parser, or untrusted-code sandbox is claimed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from importlib.metadata import version

from .canonical import clone, digest, dumps
from .gates import Registry
from .loader import load_unit
from .runtime import Runtime, AdmissionError
from .nych_adapter import operation_text, REF, REQUIREMENT

SOURCE = 'I see a red light.'
OPERATION = 'demo.write-encoded@1'
PROFILE = 'nych-runtime-one-unit/1'


def write_json(path, value):
    path.write_text(dumps(value), encoding='utf-8')


def gate(file_id, gate_id, conditions):
    return {'g8son_version': '1.0', 'file_id': file_id, 'gates': [{
        'gate_id': gate_id, 'type': 'AND', 'conditions': conditions,
        'outcomes': {'PASS': 'commit', 'FAIL': 'reject', 'INTERMEDIATE': 'review'}}]}


def eq(path, value, kind=None):
    condition = {'path': path, 'op': 'eq', 'value': value}
    if kind:
        condition['evidence_kind'] = kind
    return condition


def run(output, scenario='pass'):
    import nych
    from nych.semantic_encoding import encode_text, audit_summary
    root = Path(output).absolute()
    root.mkdir(parents=False, exist_ok=False)
    root = root.resolve()
    encoded, records = encode_text(SOURCE)
    checkpoint = {'original': SOURCE, 'encoded': encoded, 'records': records,
                  'audit': audit_summary(records)}
    (root / 'source.txt').write_text(SOURCE, encoding='utf-8')
    write_json(root / 'encoded.json', checkpoint)
    payload = encoded + '\n'
    sha = hashlib.sha256(payload.encode()).hexdigest()
    initial = {'nych': checkpoint, 'artifact': None}
    candidate = clone(initial)
    candidate['artifact'] = {'path': 'accepted.txt', 'sha256': sha}
    effect = gate('nych.effect', 'exact-operation-admission', [
        eq('/current/nych/encoded', encoded),
        eq('/operation/name', OPERATION), eq('/operation/arguments/path', 'accepted.txt'),
        {'evaluator_ref': REF, 'requirement': REQUIREMENT}, eq('/candidate/artifact/sha256', sha)])
    post = gate('nych.commit', 'fresh-final-state', [
        eq('/evidence/operation/status', 'SUCCEEDED', 'tool'),
        eq('/evidence/observation/sha256', sha, 'tool'),
        eq('/candidate/artifact/path', 'accepted.txt'), eq('/candidate/artifact/sha256', sha)])
    resources = {
        'unit.mg8': {'mg8_version': '1.0', 'unit_id': 'nych.bounded-encoding',
                     'entry': 'flow.ork', 'state': ['state.gst'], 'gates': ['commit.g8son'],
                     'trace': 'execution.qson', 'metadata': {'integration_profile': PROFILE}},
        'flow.ork': {'ork_profile': 'mg8-runtime-sequential/0.1', 'bonit': 'policy.bonit',
                     'flow': ['fresh-final-state']},
        'policy.bonit': {'bonit_profile': 'mg8-runtime/0.1', 'actors': ['offline-host'],
                         'writable_paths': ['/artifact'], 'max_attempts': 4,
                         'max_seconds': 10, 'max_commits': 1},
        'state.gst': {'gst_version': '1.0', 'state': initial},
        'commit.g8son': post, 'effect.g8son': effect,
    }
    for name, document in resources.items():
        write_json(root / name, document)
    unit = load_unit(root / 'unit.mg8')
    registry = Registry()
    registry.register(REF, operation_text, kind='mechanical', version='1')
    runtime = Runtime(root / 'runtime.sqlite', registry)

    def adapter(arguments, operation_id):
        # A fixed, host-owned directory and basename: no agent-controlled path join.
        if arguments != {'path': 'accepted.txt', 'text': payload}:
            raise ValueError('unsupported exact operation')
        fd = os.open(root / 'accepted.txt', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(arguments['text'].encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        return {'path': 'accepted.txt', 'sha256': sha, 'operation_id': operation_id}

    runtime.register_operation(OPERATION, adapter, version=PROFILE)
    sources = dict(unit.sources)
    for name in ('effect.g8son', 'source.txt', 'encoded.json'):
        sources[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    source_identity = {'unit_id': unit.manifest['unit_id'], 'resources': sources,
                       'integration_profile': PROFILE,
                       'distributions': {name: version(name) for name in ('nych', 'mg8-runtime')},
                       'implementation_sha256': {
                           'nych/' + name: hashlib.sha256((Path(nych.__file__).parent / name).read_bytes()).hexdigest()
                           for name in ('gates.py', 'semantic_encoding.py', 'semantic_registry.py', 'data/sense_registry.json')}}
    # The loader's start() deliberately has no effect-policy fields. This trusted
    # host explicitly binds its loaded unit to the runtime's existing effect API.
    run_id = runtime.create_run(unit.initial_state, unit.gate_documents, bindings=unit.bindings,
        **{k: unit.policy[k] for k in ('actors', 'writable_paths', 'max_attempts', 'max_seconds', 'max_commits')},
        allowed_operations=[OPERATION], effect_gate_documents=[effect], source_identity=source_identity)
    arguments = {'path': 'accepted.txt', 'text': payload}
    if scenario == 'fail':
        arguments['text'] += 'denied'
    elif scenario == 'unknown':
        del arguments['text']  # Missing evidence stays UNKNOWN, never false->authorization.
    proposal = runtime.propose(run_id, 'offline-host', candidate, base_version=0,
        operation={'name': OPERATION, 'arguments': arguments})
    report = runtime.evaluate(proposal, phase='effect')
    if report['outcome'] != 'PASS':
        for purpose in ('effect', 'commit'):
            try:
                runtime.authorize(proposal, purpose=purpose)
            except AdmissionError:
                pass
            else:
                raise ValueError('blocked proposal received authority')
        write_json(root / 'committed.gst', {'gst_version': '1.0', 'state': runtime.snapshot(run_id)['state']})
        runtime.store.export_qson(run_id, root / 'execution.qson')
        return {'run_id': run_id, 'status': report['outcome'], 'profile': PROFILE}
    operation = runtime.dispatch(runtime.authorize(proposal, purpose='effect'))
    write_json(root / 'operation.json', operation)
    # Read the external state anew; never use the adapter return as the observation.
    observed = hashlib.sha256((root / 'accepted.txt').read_bytes()).hexdigest()
    runtime.record_evidence(proposal, 'observation', {'path': 'accepted.txt', 'sha256': observed}, kind='tool')
    if runtime.evaluate(proposal)['outcome'] != 'PASS':
        raise ValueError('postcondition not satisfied')
    snapshot = runtime.commit(runtime.authorize(proposal))
    write_json(root / 'committed.gst', {'gst_version': '1.0', 'state': snapshot['state']})
    runtime.store.export_qson(run_id, root / 'execution.qson')
    return {'run_id': run_id, 'status': snapshot['status'], 'profile': PROFILE}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'verify'])
    parser.add_argument('directory', type=Path)
    parser.add_argument('--scenario', choices=['pass', 'fail', 'unknown'], default='pass')
    args = parser.parse_args()
    try:
        if args.action == 'run':
            result = run(args.directory, args.scenario)
        else:
            from .nych_verify import verify
            result = verify(args.directory)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, KeyError, AssertionError) as exc:
        parser.exit(1, f'verification/integration error: {exc}\n')


if __name__ == '__main__':
    main()
