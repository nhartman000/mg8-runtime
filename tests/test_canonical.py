import importlib
import unittest


class CanonicalTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module('mg8_runtime.canonical')
        except ImportError:
            self.fail('canonical serialization is not implemented')

    def test_order_and_unicode_are_stable(self):
        c = self.api()
        self.assertEqual(c.dumps({'b': '👀', 'a': 1}), '{"a":1,"b":"👀"}')
        self.assertEqual(c.digest({'b': 2, 'a': 1}), c.digest({'a': 1, 'b': 2}))

    def test_rejects_ambiguous_non_json_data(self):
        c = self.api()
        for value in [float('nan'), float('inf'), {1: 'x'}, {'x': object()}, (1, 2)]:
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                c.dumps(value)

    def test_clone_has_no_shared_mutable_objects(self):
        c = self.api()
        original = {'x': [1]}
        copied = c.clone(original)
        copied['x'].append(2)
        self.assertEqual(original, {'x': [1]})
