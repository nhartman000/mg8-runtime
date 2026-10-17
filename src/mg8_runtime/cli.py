"""Offline runnable examples and resource-bound unit entry point."""
import argparse
import json
from pathlib import Path
import sys

from .canonical import dumps
from .gates import Evaluation, Outcome, Registry
from .runtime import AdmissionError, Runtime
from .workflow import run_workflow


def _format(context, condition):
    answer = context['candidate'].get('answer')
    good = isinstance(answer, str) and answer.startswith('Photosynthesis: ') and len(answer.partition(': ')[2]) > 10
    return Evaluation(Outcome.PASS if good else Outcome.FAIL, 'subject-colon-definition check')


def _reference(context, condition):
    good = context['candidate'].get('answer') == context['current']['reference_answer']
    return Evaluation(Outcome.PASS if good else Outcome.FAIL, 'exact approved-reference comparison, not a general scientific-truth claim')


def demo(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    registry = Registry()
    registry.register('demo.subject_definition@1', _format)
    registry.register('demo.approved_reference@1', _reference)
    source = {'gate_id': 'G_DEFINITION', 'gate_name': 'Reviewed definition', 'atomic_requirements': [
        {'req_id': 'R1', 'requirement': 'Use the subject, then a colon, then its definition.'},
        {'req_id': 'R2', 'requirement': 'Match the approved reference definition exactly.'},
    ]}
    bindings = {'operator': 'AND', 'requirements': {
        'R1': {'evaluator_ref': 'demo.subject_definition@1'},
        'R2': {'evaluator_ref': 'demo.approved_reference@1'}},
        'outcomes': {'PASS': 'commit', 'FAIL': 'repeat', 'INTERMEDIATE': 'review'}}
    (output / 'requirements.g8son').write_text(dumps(source) + '\n', encoding='utf-8')
    (output / 'bindings.json').write_text(dumps(bindings) + '\n', encoding='utf-8')
    runtime = Runtime(output / 'runtime.sqlite', registry)
    state = {'answer': '', 'reference_answer': 'Photosynthesis: Plants use light to convert water and carbon dioxide into sugars, releasing oxygen.'}
    run_id = runtime.create_run(state, [source], bindings=[bindings],
        actors=['definition-agent'], writable_paths=['/answer'], max_attempts=3)
    def proposer(snapshot, previous):
        candidate = snapshot['state'].copy()
        candidate['answer'] = 'Unverified draft' if previous is None else candidate['reference_answer']
        return {'candidate': candidate}
    result = run_workflow(runtime, run_id, 'definition-agent', proposer)
    runtime.store.export_qson(run_id, output / 'execution.qson')
    (output / 'committed.gst').write_text(dumps({'gst_version': '1.0',
        'state_id': f'{run_id}:{runtime.snapshot(run_id)["version"]}',
        'state': runtime.snapshot(run_id)['state']}) + '\n', encoding='utf-8')
    result['audit'] = str((output / 'execution.qson').resolve())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog='mg8-runtime')
    commands = parser.add_subparsers(dest='command', required=True)
    demo_parser = commands.add_parser('demo', help='run offline requirement/revision/commit demo')
    demo_parser.add_argument('--output', required=True, help='new directory; never overwrites evidence')
    run_parser = commands.add_parser('run', help='execute an explicitly supported resource-bound unit')
    run_parser.add_argument('unit')
    run_parser.add_argument('--proposal', required=True)
    run_parser.add_argument('--database', required=True)
    run_parser.add_argument('--output')
    args = parser.parse_args(argv)
    try:
        if args.command == 'demo':
            result = demo(args.output)
        else:
            from .loader import load_unit
            unit = load_unit(args.unit)
            runtime = Runtime(args.database, Registry())
            run_id = unit.start(runtime)
            candidate = json.loads(Path(args.proposal).read_text(encoding='utf-8'))
            # Proposal files are state objects, not trusted evidence/permission envelopes.
            policy = runtime.store.read('run', run_id)['policy']
            def proposer(snapshot, previous):
                return {'candidate': candidate}
            result = run_workflow(runtime, run_id, policy['actors'][0], proposer)
            trace = Path(args.output) if args.output else unit.trace_path
            runtime.store.export_qson(run_id, trace)
            result['audit'] = str(trace.resolve())
        print(dumps(result))
        return 0 if result['status'] == 'COMPLETE' else 2
    except (ValueError, KeyError, OSError, AdmissionError) as exc:
        print(f'mg8-runtime: {exc}', file=sys.stderr)
        return 1
