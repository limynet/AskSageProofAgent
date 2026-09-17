"""
Tests for per-stage prompt config version history (src/prompt_history.py).

Offline: operates on a temp prompts.json/history dir via module globals.
Run from the project root with:
    .venv\\Scripts\\python.exe test_prompt_history.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import prompt_history  # noqa: E402


class TestPromptHistory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_history_dir = prompt_history.HISTORY_DIR
        self._orig_prompts_path = prompt_history.PROMPTS_PATH
        prompt_history.HISTORY_DIR = os.path.join(self._tmp, "history")
        self._prompts = os.path.join(self._tmp, "prompts.json")
        with open(self._prompts, "w", encoding="utf-8") as f:
            json.dump({"stages": {
                "s1_extract": {"version": 2, "prompts": {"P": "current"},
                               "temperature": 0.2, "max_tokens": 100},
            }}, f)
        prompt_history.PROMPTS_PATH = self._prompts

    def tearDown(self):
        prompt_history.HISTORY_DIR = self._orig_history_dir
        prompt_history.PROMPTS_PATH = self._orig_prompts_path

    def test_append_and_load(self):
        cfg = {"version": 2, "prompts": {"P": "old text"}, "temperature": 0.1}
        self.assertTrue(prompt_history.append_history("s1_extract", cfg))
        cfg["prompts"]["P"] = "mutated after archive"
        entries = prompt_history.load_history("s1_extract")
        self.assertEqual(len(entries), 1)
        # The snapshot must be immune to later mutation of the caller dict.
        self.assertEqual(entries[0]["config"]["prompts"]["P"], "old text")
        self.assertEqual(entries[0]["version"], 2)

    def test_append_is_idempotent_per_version(self):
        cfg = {"version": 3, "prompts": {"P": "x"}}
        prompt_history.append_history("s1_extract", cfg)
        self.assertFalse(prompt_history.append_history("s1_extract", cfg))
        self.assertEqual(len(prompt_history.load_history("s1_extract")), 1)

    def test_restore_bumps_version_and_archives_current(self):
        current = {"version": 5, "prompts": {"P": "current text"},
                   "temperature": 0.3}
        prompt_history.append_history("s1_extract",
                                      {"version": 4, "prompts": {"P": "older"},
                                       "temperature": 0.1})
        with open(self._prompts, "w", encoding="utf-8") as f:
            json.dump({"stages": {"s1_extract": current}}, f)

        ok, message = prompt_history.restore("s1_extract", 4)
        self.assertTrue(ok, message)
        with open(self._prompts, encoding="utf-8") as f:
            after = json.load(f)["stages"]["s1_extract"]
        self.assertEqual(after["prompts"]["P"], "older")
        self.assertEqual(after["version"], 6, "restore must bump the version")
        # The replaced current config (v5) is now archived and restorable.
        versions = [e["version"] for e in prompt_history.load_history("s1_extract")]
        self.assertIn(5, versions)

    def test_restore_unknown_version(self):
        ok, message = prompt_history.restore("s1_extract", 99)
        self.assertFalse(ok)
        self.assertIn("No archived version", message)

    def test_history_is_capped(self):
        for v in range(1, prompt_history.MAX_ENTRIES + 6):
            prompt_history.append_history("s1_extract",
                                          {"version": v, "prompts": {"P": str(v)}})
        entries = prompt_history.load_history("s1_extract")
        self.assertEqual(len(entries), prompt_history.MAX_ENTRIES)
        self.assertEqual(entries[0]["version"],
                         prompt_history.MAX_ENTRIES + 5, "newest first")


if __name__ == "__main__":
    unittest.main(verbosity=2)