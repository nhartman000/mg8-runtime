import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path


def gate(gate_id='answer'):
    return {'gate_id': gate_id, 'type': 'AND', 'conditions': [
        {'path': '/candidate/answer', 'op': 'ne', 'value': ''}],
        'outcomes': {'PASS': 'commit', 'FAIL': 'reject', 'INTERMEDIATE': 'review'}}


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = {'mg8_version': '1.0', 'unit_id': 'basic', 'entry': 'flow.ork',
                         'state': ['state.gst'], 'gates': ['gates.g8son'], 'trace': 'trace/run.qson'}
        self.ork = {'ork_profile': 'mg8-runtime-sequential/0.1', 'bonit': 'policy.bonit', 'flow': ['answer']}
        self.policy = {'bonit_profile': 'mg8-runtime/0.1', 'actors': ['agent'],
                       'writable_paths': ['/answer'], 'max_attempts': 3, 'max_seconds': 10, 'max_commits': 1}
        self.docs = {'unit.mg8': self.manifest, 'flow.ork': self.ork, 'policy.bonit': self.policy,
                     'state.gst': {'gst_version': '1.0', 'state_id': 'basic.state', 'state': {'answer': ''}},
                     'gates.g8son': {'g8son_version': '1.0', 'file_id': 'basic.gates', 'gates': [gate()]}}
        self.save()

    def save(self):
        for name, value in self.docs.items():
            (self.root / name).write_text(json.dumps(value), encoding='utf-8')

    def load(self, **kwargs):
        try:
            loader = importlib.import_module('mg8_runtime.loader')
        except ImportError:
            self.fail('resource-bound loader is not implemented')
        return loader.load_unit(self.root / 'unit.mg8', **kwargs)

    def test_canonical_snapshot_start_and_no_side_effects(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        unit = self.load()
        self.assertEqual(unit.initial_state, {'answer': ''})
        self.assertEqual(unit.manifest, self.manifest)
        self.assertEqual(unit.gate_documents, [self.docs['gates.g8son']])
        self.assertEqual(unit.bindings, [{}])
        self.assertEqual(unit.trace_path, self.root / 'trace/run.qson')
        self.assertEqual(unit.sources, {name: hashlib.sha256(raw).hexdigest() for name, raw in before.items()})
        unit.initial_state['answer'] = 'tampered'
        unit.policy['actors'].append('intruder')
        self.assertEqual(unit.initial_state['answer'], '')
        self.assertEqual(unit.policy['actors'], ['agent'])
        (self.root / 'state.gst').write_text('{}')
        try:
            from mg8_runtime.runtime import Runtime
        except ImportError as exc:
            self.skipTest('runtime integration not ready: ' + str(exc))
        from mg8_runtime.gates import Registry
        rt = Runtime(self.root / 'runtime.sqlite', Registry())
        run = unit.start(rt)
        proposal = rt.propose(run, 'agent', {'answer': 'A local answer.'}, base_version=0)
        self.assertEqual(rt.evaluate(proposal)['outcome'], 'PASS')
        rt.commit(rt.authorize(proposal))
        self.assertEqual(rt.snapshot(run)['state']['answer'], 'A local answer.')
        self.assertFalse((self.root / 'trace').exists())
        for name, raw in before.items():
            if name != 'state.gst':
                self.assertEqual((self.root / name).read_bytes(), raw)

    def test_manifest_versions_keys_suffixes_and_duplicate_refs(self):
        for key, value in [('mg8_version', '2.0'), ('unit_id', ''), ('entry', 'flow.json'),
                           ('state', []), ('state', ['state.gst', 'other.gst']),
                           ('gates', ['gates.g8son', 'gates.g8son']), ('trace', 'trace.txt')]:
            with self.subTest(key=key, value=value):
                original = self.manifest[key]
                self.manifest[key] = value
                self.save()
                with self.assertRaises(ValueError):
                    self.load()
                self.manifest[key] = original
        del self.manifest['trace']
        self.save()
        with self.assertRaises(ValueError):
            self.load()

    def test_resource_confinement_before_reading(self):
        for target, key in [(self.manifest, 'entry'), (self.manifest, 'trace'), (self.ork, 'bonit')]:
            for ref in ['../secret', '/secret', 'nested/../../secret']:
                original = target[key]
                target[key] = ref
                self.save()
                with self.subTest(key=key, ref=ref), self.assertRaises(ValueError):
                    self.load()
                target[key] = original
        for key in ['state', 'gates']:
            original = self.manifest[key]
            self.manifest[key] = ['../secret' + ('.gst' if key == 'state' else '.g8son')]
            self.save()
            with self.assertRaises(ValueError):
                self.load()
            self.manifest[key] = original
        self.save()
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / 'secret.gst'
            secret.write_text('{"state": {}}')
            (self.root / 'state.gst').unlink()
            (self.root / 'state.gst').symlink_to(secret)
            with self.assertRaises(ValueError):
                self.load()

    def test_json_is_strict_bounded_and_object_only(self):
        for raw in ['{"state":{},"state":{}}', '{"state":{"x":NaN}}',
                    '{"state":{"x":1e999}}', '{bad', '[]',
                    '{"state":' + '[' * 100 + '0' + ']' * 100 + '}']:
            (self.root / 'state.gst').write_text(raw)
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                self.load()
        self.save()
        with self.assertRaises(ValueError):
            self.load(max_resource_bytes=10)
        for bound in [0, -1, True, 1.5]:
            with self.assertRaises(ValueError):
                self.load(max_resource_bytes=bound)

    def test_explicit_profiles_and_policy_no_predicates(self):
        for document, key, value in [(self.ork, 'ork_profile', '0.3'),
                                     (self.ork, 'blocks', []),
                                     (self.policy, 'bonit_profile', 'unknown'),
                                     (self.policy, 'conditions', []),
                                     (self.policy, 'max_attempts', True),
                                     (self.policy, 'actors', []),
                                     (self.policy, 'writable_paths', ['not-pointer']),
                                     (self.policy, 'bindings', {'unknown.g8son': {}})]:
            existed, original = key in document, document.get(key)
            document[key] = value
            self.save()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load()
            if existed:
                document[key] = original
            else:
                del document[key]

    def test_historical_bindings_are_explicit_and_preserve_source(self):
        self.docs['gates.g8son'] = {'gate_id': 'answer', 'atomic_requirements': [
            {'req_id': 'R1', 'requirement': 'Answer must not be empty.'}]}
        self.save()
        with self.assertRaises(ValueError):
            self.load()
        self.policy['bindings'] = {'gates.g8son': {
            'operator': 'AND', 'outcomes': gate()['outcomes'],
            'requirements': {'R1': {'path': '/candidate/answer', 'op': 'ne', 'value': ''}}}}
        self.save()
        unit = self.load()
        self.assertEqual(unit.gate_documents[0], self.docs['gates.g8son'])
        self.assertEqual(unit.bindings[0], self.policy['bindings']['gates.g8son'])

    def test_unknown_resource_versions_and_global_gate_duplicates(self):
        for name, key in [('state.gst', 'gst_version'), ('gates.g8son', 'g8son_version')]:
            self.docs[name][key] = 'unknown'
            self.save()
            with self.assertRaises(ValueError):
                self.load()
            self.docs[name][key] = '1.0'
        self.docs['other.g8son'] = self.docs['gates.g8son']
        self.manifest['gates'].append('other.g8son')
        self.save()
        with self.assertRaisesRegex(ValueError, 'duplicate gate'):
            self.load()

    def test_symlinks_rejected_for_each_resource_and_trace_parent(self):
        with tempfile.TemporaryDirectory() as outside:
            outside_root = Path(outside)
            for name in ['unit.mg8', 'flow.ork', 'policy.bonit', 'state.gst', 'gates.g8son']:
                self.save()
                target = outside_root / name
                target.write_text(json.dumps(self.docs[name]))
                (self.root / name).unlink()
                (self.root / name).symlink_to(target)
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'symlink'):
                    self.load()
                (self.root / name).unlink()
            self.save()
            (self.root / 'trace').symlink_to(outside_root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                self.load()

    def test_example_is_locally_evaluable_without_runtime(self):
        from mg8_runtime.loader import load_unit
        from mg8_runtime.gates import GateSet, Registry
        example = Path(__file__).resolve().parents[1] / 'examples/basic'
        unit = load_unit(example / 'unit.mg8')
        proposal = json.loads((example / 'proposal.json').read_text())
        gates = GateSet(unit.gate_documents[0], unit.bindings[0])
        self.assertIsInstance(proposal.get('answer'), str)
        context = {'current': unit.initial_state, 'candidate': proposal, 'evidence': {}}
        self.assertEqual(gates.evaluate(context, Registry())['outcome'], 'PASS')
        context['candidate'] = {'answer': ''}
        self.assertEqual(gates.evaluate(context, Registry())['outcome'], 'FAIL')
        self.assertFalse(unit.trace_path.exists())

    def test_gate_coverage_requires_exact_order_and_unique_ids(self):
        second = gate('second')
        self.docs['gates.g8son']['gates'][0]['outcomes']['PASS'] = 'continue'
        self.docs['gates.g8son']['gates'].append(second)
        for flow in [['answer'], ['second', 'answer'], ['answer', 'answer'], ['answer', 'second', 'unknown']]:
            self.ork['flow'] = flow
            self.save()
            with self.subTest(flow=flow), self.assertRaises(ValueError):
                self.load()
        self.ork['flow'] = ['answer', 'second']
        self.save()
        self.assertEqual(len(self.load().gate_documents[0]['gates']), 2)
        self.docs['gates.g8son']['gates'][1]['gate_id'] = 'answer'
        self.save()
        with self.assertRaises(ValueError):
            self.load()


if __name__ == '__main__':
    unittest.main()
