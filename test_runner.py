"""
Test suite for the seven-stage review runner (src/runner.py).

Everything here runs offline: the LLM client is a data-driven stub, so no
model and no network are required. Run from the project root with:

    .venv\\Scripts\\python.exe test_runner.py

ASCII/English only.
"""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from pipeline import PipelineState  # noqa: E402
from runner import DEFAULT_GATED, PERSONA_STAGES, ReviewRun  # noqa: E402


def analysis_response():
    """A canned analysis response the stub returns for every call."""
    return (
        "Analyzed the manuscript. **OVERALL ASSESSMENT: [PARTIALLY_COMPLIANT]**\n"
        "| p.3 | bad cite | et al misuse | fix | APA 7th | MODERATE |\n"
        "| p.7 | x | missing ref | add | ARI | CRITICAL |\n"
    )


class StubLLM:
    """Data-driven LLM client stub returning a fixed analysis response."""

    def __init__(self, delay=0.0, fail_after=None):
        self.delay = delay
        self.fail_after = fail_after
        self.calls = []
        self._lock = threading.Lock()

    def chat_completion(self, messages, temperature=0.1, max_tokens=4000, **kwargs):
        with self._lock:
            self.calls.append(messages)
            n = len(self.calls)
        if self.delay:
            time.sleep(self.delay)
        if self.fail_after is not None and n > self.fail_after:
            raise RuntimeError("stub failure on call {0}".format(n))
        return analysis_response()

    def call_count(self):
        with self._lock:
            return len(self.calls)


class TestSelection(unittest.TestCase):
    """Selection normalization accepts personas and stage keys."""

    def test_persona_names_map_to_gated_stages(self):
        self.assertEqual(PERSONA_STAGES["citation"], "s3_citations")
        self.assertEqual(PERSONA_STAGES["apa"], "s4_sme")
        self.assertEqual(PERSONA_STAGES["sme"], "s5_copyedit")
        self.assertEqual(list(DEFAULT_GATED),
                         ["s3_citations", "s4_sme", "s5_copyedit"])

    def test_invalid_selection_raises(self):
        with self.assertRaises(ValueError):
            ReviewRun(StubLLM(), selected=["nope"])


class TestHappyPath(unittest.TestCase):
    """Selected stages run to completion on the daemon thread."""

    def test_selected_gated_runs_with_pre_and_post(self):
        stub = StubLLM()
        pipeline = PipelineState()
        run = ReviewRun(stub, selected=["s3_citations"], pipeline=pipeline)

        started = run.start("Some short manuscript text.")
        self.assertTrue(started)
        self.assertTrue(run.join(15.0), "worker did not settle in time")
        self.assertFalse(run.is_running())

        self.assertEqual(pipeline.get("s1_extract").status, "done")
        self.assertEqual(pipeline.get("s2_cross_section").status, "done")
        self.assertEqual(pipeline.get("s3_citations").status, "done")
        self.assertEqual(pipeline.get("s4_sme").status, "skipped")
        self.assertEqual(pipeline.get("s5_copyedit").status, "skipped")
        self.assertEqual(pipeline.get("s6_dedup").status, "done")
        self.assertEqual(pipeline.get("s7_report").status, "done")

        result = run.result()
        self.assertIn("s3_citations", result)
        self.assertEqual(len(result["s3_citations"]["findings"]), 2)
        self.assertEqual(run.findings_count(), 2)

    def test_default_selection_runs_all_gated(self):
        stub = StubLLM()
        pipeline = PipelineState()
        run = ReviewRun(stub, selected=None, pipeline=pipeline)
        run.start("text")
        self.assertTrue(run.join(15.0))
        for stage in ("s3_citations", "s4_sme", "s5_copyedit"):
            self.assertEqual(pipeline.get(stage).status, "done", stage)
        self.assertEqual(pipeline.get("s7_report").status, "done")
        self.assertGreaterEqual(run.findings_count(), 0)

    def test_report_text_is_captured(self):
        run = ReviewRun(StubLLM(), selected=["s5_copyedit"])
        run.start("text")
        self.assertTrue(run.join(15.0))
        report = run.report_text()
        self.assertIsInstance(report, str)


class TestIdempotentStart(unittest.TestCase):
    def test_second_start_is_ignored_while_running(self):
        gate = threading.Event()
        stub = StubLLM()
        orig = stub.chat_completion

        def gated(*a, **k):
            gate.wait(5.0)
            return analysis_response()
        stub.chat_completion = gated

        run = ReviewRun(stub, selected=["s3_citations"])
        try:
            self.assertTrue(run.start("text"))
            # The worker is blocked inside the first stage; a second start is
            # a no-op.
            self.assertFalse(run.start("text"))
            stub.chat_completion = orig
            gate.set()
            run.join(10.0)
            self.assertFalse(run.is_running())
        finally:
            gate.set()
            run.join(10.0)


class TestCancelKeepsPartial(unittest.TestCase):
    def test_cancel_at_stage_boundary_keeps_partials(self):
        stub = StubLLM(delay=0.04)
        pipeline = PipelineState()
        run = ReviewRun(stub, selected=["s3_citations", "s4_sme"], pipeline=pipeline)
        run.start("text")
        time.sleep(0.02)
        run.cancel()
        self.assertTrue(run.join(15.0))
        self.assertFalse(run.is_running())
        self.assertTrue(run.progress_snapshot()["cancel_requested"])
        statuses = [pipeline.get(stage).status for stage in pipeline.names()]
        self.assertIn("done", statuses)
        self.assertTrue(run.findings_count() >= 0)


class TestFailureStopsRun(unittest.TestCase):
    def test_stage_failure_marks_failed(self):
        stub = StubLLM(fail_after=0)
        pipeline = PipelineState()
        run = ReviewRun(stub, selected=["s3_citations"], pipeline=pipeline)
        run.start("text")
        self.assertTrue(run.join(15.0))
        statuses = [pipeline.get(stage).status for stage in pipeline.names()]
        self.assertIn("failed", statuses)
        self.assertTrue(run.findings_count() >= 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)