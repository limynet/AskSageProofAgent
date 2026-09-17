"""
Tests for the reference document registry and loader (src/references.py).

Offline: no network; the registry is the real configs/references.json and the
loader degrades gracefully when the on-disk files are absent.

Run from the project root with:
    .venv\\Scripts\\python.exe test_references.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import references  # noqa: E402


class TestRegistry(unittest.TestCase):
    def test_registry_has_three_documents(self):
        reg = references.load_registry()
        docs = reg.get("documents") or []
        self.assertEqual(len(docs), 3)
        keys = [d.get("key") for d in docs]
        self.assertEqual(keys, ["ari_manual", "army_ar_rag", "dtic_regs"])

    def test_documents_not_loaded_when_files_absent(self):
        # On a clean checkout the reference files are not supplied yet.
        for doc in references.load_registry().get("documents") or []:
            self.assertIn("loaded", doc)
            self.assertIn("file_abs", doc)

    def test_attachments_empty_for_no_keys(self):
        self.assertEqual(references.attachments_for([]), "")

    def test_missing_document_renders_marker(self):
        block = references.attachments_for(["ari_manual"])
        self.assertIn("NOT LOADED", block)


class TestWithTempFile(unittest.TestCase):
    def test_loaded_document_injected(self):
        # Point the registry at a temp file by monkeypatching the path.
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("ARI rule 25-1: release criteria.")
        original_path = references.REGISTRY_PATH
        original_root = references.ROOT_DIR
        try:
            tmp_reg = os.path.join(tempfile.gettempdir(), "refs_test.json")
            with open(tmp_reg, "w", encoding="utf-8") as f:
                json.dump({"documents": [
                    {"key": "ari_manual", "title": "ARI Manual",
                     "file": os.path.basename(path)},
                ]}, f)
            references.REGISTRY_PATH = tmp_reg
            references.ROOT_DIR = os.path.dirname(path)
            reg = references.load_registry()
            self.assertTrue(reg["documents"][0]["loaded"])
            block = references.attachments_for(["ari_manual"])
            self.assertIn("ARI rule 25-1", block)
            self.assertNotIn("NOT LOADED", block)
        finally:
            references.REGISTRY_PATH = original_path
            references.ROOT_DIR = original_root
            os.remove(path)
            if os.path.exists(tmp_reg):
                os.remove(tmp_reg)

    def test_fallback_extension_md_is_loaded(self):
        # The registry names .txt, but a same-basename .md must be found.
        fd, path = tempfile.mkstemp(suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("Army AR rule: clearance before release.")
        registered = os.path.splitext(path)[0] + ".txt"
        original_path = references.REGISTRY_PATH
        original_root = references.ROOT_DIR
        try:
            tmp_reg = os.path.join(tempfile.gettempdir(), "refs_test_md.json")
            with open(tmp_reg, "w", encoding="utf-8") as f:
                json.dump({"documents": [
                    {"key": "army_ar_rag", "title": "Army AR",
                     "file": os.path.basename(registered)},
                ]}, f)
            references.REGISTRY_PATH = tmp_reg
            references.ROOT_DIR = os.path.dirname(path)
            reg = references.load_registry()
            self.assertTrue(reg["documents"][0]["loaded"])
            self.assertTrue(reg["documents"][0]["file_abs"].endswith(".md"))
            text = references.document_text("army_ar_rag")
            self.assertIn("clearance before release", text)
        finally:
            references.REGISTRY_PATH = original_path
            references.ROOT_DIR = original_root
            os.remove(path)
            if os.path.exists(tmp_reg):
                os.remove(tmp_reg)


if __name__ == "__main__":
    unittest.main(verbosity=2)