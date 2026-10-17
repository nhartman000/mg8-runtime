import unittest
from mg8_runtime.gates import Evaluation, GateSet, Outcome, Registry
from tests.test_runtime import gates


class AssessmentProvenanceTests(unittest.TestCase):
    def test_canonical_source_rejects_unknown_root_and_conflicting_order(self):
        doc = gates()
        with self.assertRaises(ValueError):
            GateSet(dict(doc, hidden_policy='ignored'))
        import copy
        first = doc['gates'][0]
        second = copy.deepcopy(first)
        first['order'] = 2
        second.update(gate_id='second', order=1)
        doc['gates'].append(second)
        with self.assertRaises(ValueError):
            GateSet(doc)

    def test_binding_cannot_replace_an_authored_mechanical_condition(self):
        doc = gates()
        for replacement in [{'value': False}, {'path': '/current/verified'}, {'op': 'ne'}, {'evaluator_ref': 'ignore-source@1'}]:
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                GateSet(doc, {'requirements': {'admission:0': replacement}})

    def test_model_assessment_cannot_relabel_its_evaluator_identity(self):
        registry = Registry()
        registry.register('review@1', lambda c, r: Evaluation(Outcome.PASS, 'assessed',
            {'evaluator': {'kind': 'tool', 'ref': 'forged'}}), kind='model', version='rubric-1')
        doc = gates()
        doc['gates'][0]['conditions'] = [{'req_id': 'R1', 'requirement': 'Reads simply', 'evaluator_ref': 'review@1'}]
        report = GateSet(doc).evaluate({'candidate': {}}, registry)
        record = report['gates'][0]['requirements'][0]
        self.assertEqual(record['evidence']['evaluator'], {'kind': 'model', 'ref': 'review@1', 'version': 'rubric-1'})
        self.assertEqual(record['condition']['requirement'], 'Reads simply')
        self.assertEqual(record['condition']['evaluator_ref'], 'review@1')
