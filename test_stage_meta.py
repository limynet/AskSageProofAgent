"""
Tests for the stage metadata manifest (src/stage_meta.py).

Run from the project root with:
    .venv\\Scripts\\python.exe test_stage_meta.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import stage_meta  # noqa: E402


class TestStageOrder(unittest.TestCase):
    def test_seven_stages_in_original_order(self):
        self.assertEqual(
            stage_meta.STAGE_ORDER,
            ["s1_extract", "s2_cross_section", "s3_citations", "s4_sme",
             "s5_copyedit", "s6_dedup", "s7_report"],
        )

    def test_display_names(self):
        self.assertEqual(stage_meta.stage_title("s3_citations"),
                         "Citations & APA Review")
        self.assertEqual(stage_meta.stage_title("s4_sme"),
                         "SME + Statistics Review")
        self.assertEqual(stage_meta.stage_title("s5_copyedit"),
                         "CopyEdit + Bias + Originality")


class TestPromptKeysExist(unittest.TestCase):
    def test_every_referenced_prompt_key_exists_in_prompts_json(self):
        prompts_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "configs", "prompts.json")
        with open(prompts_path, encoding="utf-8") as f:
            store = json.load(f)
        for stage in stage_meta.STAGE_ORDER:
            cfg = store["stages"].get(stage) or {}
            prompts = cfg.get("prompts") or {}
            for key in stage_meta.all_prompt_keys_for_stage(stage):
                self.assertIn(key, prompts, "%s missing in stage %s" % (key, stage))
                self.assertTrue(str(prompts[key]).strip(), "%s empty" % key)

    def test_s3_flow_has_branch_group(self):
        steps = stage_meta.sub_steps("s3_citations")
        labels = [s["label"] for s in steps]
        self.assertEqual(labels, ["Analyze", "Compliance label",
                                  "Branch response", "Final format"])
        branch = steps[2]
        self.assertEqual(branch["kind"], "group")
        self.assertEqual(len(branch["prompt_keys"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)