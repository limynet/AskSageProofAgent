"""
Test suite for the seven-stage pipeline state machine (src/pipeline.py).

Plain unittest, no third-party dependencies, no I/O, no network. Run from
the project root with:

    .venv\\Scripts\\python.exe test_pipeline.py

ASCII only, English only, no emoji.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from pipeline import (  # noqa: E402
    AGENT_STAGES,
    VALID_STAGES,
    VALID_STATUSES,
    PipelineState,
    StageState,
)


class TestConstants(unittest.TestCase):
    """The module constants match the documented contract."""

    def test_stage_and_status_constants(self):
        self.assertEqual(
            VALID_STAGES,
            [
                "s1_extract",
                "s2_cross_section",
                "s3_citations",
                "s4_sme",
                "s5_copyedit",
                "s6_dedup",
                "s7_report",
            ],
        )
        self.assertEqual(
            VALID_STATUSES,
            [
                "pending",
                "running",
                "done",
                "skipped",
                "failed",
                "cancelled",
                "awaiting_approval",
            ],
        )
        self.assertEqual(AGENT_STAGES, ["s3_citations", "s4_sme", "s5_copyedit"])


class TestInitialState(unittest.TestCase):
    """A fresh pipeline starts fully pending."""

    def test_init_all_pending(self):
        state = PipelineState()
        self.assertEqual(state.names(), VALID_STAGES)
        for stage in state.stages:
            self.assertIsInstance(stage, StageState)
            self.assertEqual(stage.status, "pending")
            self.assertIsNone(stage.started_at)
            self.assertIsNone(stage.finished_at)
            self.assertEqual(stage.count, 0)
            self.assertEqual(stage.detail, "")
        self.assertEqual(state.next_action(), "idle")
        self.assertEqual(state.summary_status(), "pending")


class TestStatusTransitions(unittest.TestCase):
    """Timestamps are stamped on the documented transitions."""

    def test_running_stamps_started_and_leaving_running_stamps_finished(self):
        state = PipelineState()
        stage = state.set_status("s1_extract", "running")
        self.assertEqual(stage.status, "running")
        self.assertIsNotNone(stage.started_at)
        self.assertIsNone(stage.finished_at)

        stage = state.set_status("s1_extract", "done", "parsed 3 pages")
        self.assertEqual(stage.status, "done")
        self.assertIsNotNone(stage.finished_at)
        self.assertEqual(stage.detail, "parsed 3 pages")

    def test_started_at_is_not_overwritten_on_rerun(self):
        state = PipelineState()
        first = state.set_status("s2_cross_section", "running").started_at
        state.set_status("s2_cross_section", "done")
        second = state.set_status("s2_cross_section", "running").started_at
        self.assertEqual(first, second)

    def test_awaiting_approval_round_trip(self):
        state = PipelineState()
        state.set_status("s2_cross_section", "running")
        state.set_status("s2_cross_section", "done", "12 rule hits")
        state.set_count("s2_cross_section", 12)
        state.set_status("s3_citations", "awaiting_approval", "awaiting user")
        self.assertEqual(state.get("s2_cross_section").count, 12)
        self.assertEqual(state.next_action(), "awaiting_approval")

    def test_invalid_status_and_stage_rejected(self):
        state = PipelineState()
        with self.assertRaises(ValueError):
            state.set_status("s1_extract", "finished")
        with self.assertRaises(ValueError):
            state.set_status("not_a_stage", "running")
        with self.assertRaises(ValueError):
            state.get("not_a_stage")
        # The failed call must not have mutated anything.
        self.assertEqual(state.get("s1_extract").status, "pending")


class TestApprovableAgents(unittest.TestCase):
    """approvable_agents is gated on the pre-review stages and pending status."""

    def test_empty_until_gate_done(self):
        state = PipelineState()
        self.assertEqual(state.approvable_agents(False), [])
        self.assertEqual(state.approvable_agents(True), list(AGENT_STAGES))

    def test_only_pending_agent_stages_are_returned(self):
        state = PipelineState()
        state.set_status("s3_citations", "running")
        state.set_status("s4_sme", "done")
        self.assertEqual(state.approvable_agents(True), ["s5_copyedit"])
        self.assertEqual(state.approvable_agents(False), [])


class TestNextAction(unittest.TestCase):
    """next_action reports the most urgent condition first."""

    def test_priority_order(self):
        state = PipelineState()
        state.set_status("s1_extract", "running")
        self.assertEqual(state.next_action(), "running")

        state.set_status("s5_copyedit", "awaiting_approval")
        self.assertEqual(state.next_action(), "awaiting_approval")

        state.set_status("s2_cross_section", "failed", "bad file")
        self.assertEqual(state.next_action(), "failed")

    def test_done_when_final_report_done(self):
        state = PipelineState()
        state.set_status("s2_cross_section", "done")
        state.set_status("s7_report", "done")
        self.assertEqual(state.next_action(), "done")


class TestSummaryStatus(unittest.TestCase):
    """summary_status only reports done when something upstream completed."""

    def test_done_requires_a_completed_upstream_stage(self):
        state = PipelineState()
        state.set_status("s7_report", "done")
        self.assertEqual(state.summary_status(), "done")

        state.set_status("s2_cross_section", "done")
        self.assertEqual(state.summary_status(), "done")

    def test_agent_done_alone_is_enough(self):
        state = PipelineState()
        state.set_status("s4_sme", "done")
        state.set_status("s7_report", "done")
        self.assertEqual(state.summary_status(), "done")

    def test_raw_status_is_reflected_when_not_done(self):
        state = PipelineState()
        state.set_status("s7_report", "cancelled", "cancelled by user")
        self.assertEqual(state.summary_status(), "cancelled")


class TestResetAndSerialization(unittest.TestCase):
    """reset() clears everything and to_dict() round-trips."""

    def test_reset_clears_all_fields(self):
        state = PipelineState()
        state.set_status("s2_cross_section", "running")
        state.set_status("s2_cross_section", "done", "5 rule hits")
        state.set_count("s2_cross_section", 5)
        state.set_status("s7_report", "done")
        state.reset()

        for stage in state.stages:
            self.assertEqual(stage.status, "pending")
            self.assertIsNone(stage.started_at)
            self.assertIsNone(stage.finished_at)
            self.assertEqual(stage.count, 0)
            self.assertEqual(stage.detail, "")

    def test_to_dict_is_json_serializable_and_round_trips(self):
        state = PipelineState()
        state.set_status("s1_extract", "running")
        state.set_status("s1_extract", "done", "1 file")
        state.set_status("s2_cross_section", "done", "3 rule hits")
        state.set_count("s2_cross_section", 3)
        state.set_status("s3_citations", "awaiting_approval", "user gate")

        payload = state.to_dict()
        text = json.dumps(payload)
        self.assertIn("stages", payload)
        self.assertIn("next_action", payload)
        self.assertEqual(len(payload["stages"]), len(VALID_STAGES))
        self.assertEqual(payload["next_action"], "awaiting_approval")

        restored = PipelineState.from_dict(json.loads(text))
        self.assertEqual(restored.to_dict()["stages"], payload["stages"])
        self.assertEqual(restored.get("s2_cross_section").count, 3)
        self.assertEqual(restored.get("s3_citations").detail, "user gate")

    def test_from_dict_ignores_unknown_stages(self):
        restored = PipelineState.from_dict(
            {"stages": [{"name": "ghost", "status": "done"}]}
        )
        self.assertEqual(restored.names(), VALID_STAGES)
        self.assertEqual(restored.get("s1_extract").status, "pending")


if __name__ == "__main__":
    unittest.main(verbosity=2)