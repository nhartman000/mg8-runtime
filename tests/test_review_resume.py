import tempfile
import unittest
from pathlib import Path

from mg8_runtime.gates import Registry
from mg8_runtime.runtime import AdmissionError, Runtime
from mg8_runtime.workflow import run_workflow
from tests.test_runtime import gates


class ReviewResumeTests(unittest.TestCase):
    def test_host_can_resume_review_without_reviving_old_permits(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = Runtime(Path(tmp) / 'runtime.sqlite', Registry())
            run = rt.create_run({'verified': False}, [gates()], actors=['agent'], writable_paths=['/verified'])
            p = rt.propose(run, 'agent', {'verified': True}, base_version=0)
            rt.evaluate(p)
            old_permit = rt.authorize(p)
            result = run_workflow(rt, run, 'agent', lambda s, p: {'candidate': {}})
            self.assertEqual(result['status'], 'REVIEW')
            self.assertTrue(callable(getattr(rt, 'resume', None)), 'trusted review-resume boundary is not implemented')
            rt.resume(run, reason='operator requests another bounded attempt')
            with self.assertRaises(AdmissionError):
                rt.commit(old_permit)
            self.assertEqual(rt.snapshot(run)['attempts'], 2, 'resume must not reset loop bounds')
            rt.cancel(run)
            with self.assertRaises(AdmissionError):
                rt.resume(run, reason='cannot resume a cancelled run')
