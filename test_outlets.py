"""
Tests for the named API outlets registry (src/outlets.py).

Offline: no network. The client is only constructed; no request is sent.
Run from the project root with:
    .venv\\Scripts\\python.exe test_outlets.py
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import outlets  # noqa: E402


class TestRegistry(unittest.TestCase):
    def test_default_registry_has_three_outlets(self):
        keys = outlets.outlet_keys()
        self.assertEqual(keys, ["local", "custom", "genai-mil"])

    def test_titles_fall_back_to_key(self):
        titles = outlets.outlet_titles()
        self.assertEqual(titles["local"], "Local (Bonsai)")

    def test_genai_mil_entry_has_no_secret(self):
        cfg = outlets.resolve_outlet("genai-mil")
        # The registry only names env vars; no key literal in the JSON.
        self.assertEqual(cfg["base_url"], "https://api.genai.mil/v1")
        self.assertEqual(cfg["api_key"], "")
        # The repo file must not contain a key value.
        with open(outlets.OUTLETS_PATH, encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn("api.genai.mil/v1\n      \"api_key_default\": \"sk", raw)
        self.assertNotIn("api_key_default\": \"wise", raw)


class TestResolve(unittest.TestCase):
    def test_env_wins_over_default(self):
        with mock.patch.dict(os.environ, {"LOCAL_MODEL": "other-model"}):
            cfg = outlets.resolve_outlet("local")
        self.assertEqual(cfg["model"], "other-model")
        self.assertTrue(cfg["base_url"])

    def test_default_used_without_env(self):
        env = {k: v for k, v in os.environ.items() if k != "LOCAL_MODEL"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = outlets.resolve_outlet("local")
        self.assertEqual(cfg["model"], "bonsai-1.7b")

    def test_unknown_key_returns_none(self):
        self.assertIsNone(outlets.resolve_outlet("no-such-outlet"))
        self.assertIsNone(outlets.build_client("no-such-outlet"))


class TestSecretsLoader(unittest.TestCase):
    """Keys stored in a temp secrets/ folder are picked up by resolve_outlet,
    and real environment variables still win."""

    def _patch_secrets(self):
        import tempfile

        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "outlets.env"), "w", encoding="utf-8") as f:
            f.write("GENAI_MIL_API_KEY=secret-abc\nGENAI_MIL_MODEL=gemini-2.5-flash\n")
        self._orig_dir = outlets.SECRETS_DIR
        self._orig_flag = outlets._secrets_loaded
        outlets.SECRETS_DIR = tmp
        outlets._secrets_loaded = False

    def tearDown(self):
        outlets.SECRETS_DIR = getattr(self, "_orig_dir", outlets.SECRETS_DIR)
        outlets._secrets_loaded = getattr(self, "_orig_flag", False)

    def test_secret_loaded_from_file(self):
        self._patch_secrets()
        env = {k: v for k, v in os.environ.items()
               if k not in ("GENAI_MIL_API_KEY", "GENAI_MIL_MODEL")}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = outlets.resolve_outlet("genai-mil")
        self.assertEqual(cfg["api_key"], "secret-abc")

    def test_real_env_wins_over_secrets_file(self):
        self._patch_secrets()
        with mock.patch.dict(os.environ, {"GENAI_MIL_API_KEY": "env-wins"}):
            cfg = outlets.resolve_outlet("genai-mil")
        self.assertEqual(cfg["api_key"], "env-wins")


class TestBuildClient(unittest.TestCase):
    def test_local_client_constructs_without_network(self):
        client = outlets.build_client("local")
        self.assertIsNotNone(client)
        self.assertEqual(client.model, os.getenv("LOCAL_MODEL", "bonsai-1.7b"))
        self.assertTrue(client.base_url)
        self.assertTrue(hasattr(client, "chat_completion"))

    def test_custom_outlet_without_base_url_is_rejected(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CUSTOM_API_BASE",)}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                outlets.build_client("custom")


if __name__ == "__main__":
    unittest.main(verbosity=2)