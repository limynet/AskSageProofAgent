"""
Tests for the prompt editor save behavior in dashboard.py (F1/F2/Part 1).

The save callback persists per-node prompt edits atomically and (Part 1)
persists the reference-document attachment checklist. These tests drive the
callback functions directly; the Dash ctx-dependent by-key path is exercised
through the documented fallback (positional zip) which the direct call uses.

Offline: no network, no model. Run from the project root with:
    .venv\\Scripts\\python.exe test_dashboard_save.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("LOCAL_API_BASE", "http://localhost:8080/v1")
os.environ.setdefault("LOCAL_MODEL", "bonsai-1.7b")

import dashboard  # noqa: E402


def _walk_ids(component):
    """Yield every id in a Dash component tree (dict or string ids)."""
    if not hasattr(component, "id"):
        return
    if component.id is not None:
        yield component.id
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk_ids(child)
    elif children is not None and hasattr(children, "id"):
        yield from _walk_ids(children)


class TestStageDetailNoSelfNesting(unittest.TestCase):
    """Regression: clicking a stage must not nest the panel inside itself.

    pip_stage_focus writes Output("stage-detail", "children"). The inner
    body it returns must not itself carry id="stage-detail", or every click
    embeds another full copy of the panel (the "multiple box" bug).
    """

    ROW = {
        "name": "s1_extract",
        "status": "pending",
        "count": 0,
        "detail": "",
    }

    def test_inner_body_has_no_stage_detail_id(self):
        body = dashboard._stage_detail_body(self.ROW, None)
        self.assertTrue(body, "inner body must render content")
        for cid in _walk_ids_list(body):
            self.assertNotEqual(cid, "stage-detail")

    def test_wrapper_render_keeps_single_id(self):
        panel = dashboard._render_stage_detail(self.ROW, None)
        self.assertEqual(panel.id, "stage-detail")
        ids = list(_walk_ids_list(panel.children))
        self.assertNotIn("stage-detail", ids)


class TestReferenceUploadSave(unittest.TestCase):
    """Regression: uploading a reference manual stores it under
    data/reference/ with the registry's base name and any supported ext."""

    def test_save_reference_document_txt(self):
        import base64 as b64
        import json as jsonlib
        import references

        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        registered = os.path.splitext(path)[0] + ".txt"
        tmp_reg = os.path.join(tempfile.gettempdir(), "refs_upload_test.json")
        with open(tmp_reg, "w", encoding="utf-8") as f:
            jsonlib.dump({"documents": [
                {"key": "ari_manual", "title": "ARI Manual",
                 "file": os.path.basename(registered)},
            ]}, f)
        original_path = references.REGISTRY_PATH
        original_root = references.ROOT_DIR
        try:
            references.REGISTRY_PATH = tmp_reg
            references.ROOT_DIR = os.path.dirname(path)
            payload = b64.b64encode(b"ARI rule 25-1: release criteria.").decode()
            ok, message = dashboard._save_reference_document(
                "ari_manual", "manual.txt", "data:text/plain;base64," + payload)
            self.assertTrue(ok, message)
            self.assertTrue(os.path.isfile(registered))
            reg = references.load_registry()
            self.assertTrue(reg["documents"][0]["loaded"])
            self.assertIn("ari rule 25-1", references.document_text("ari_manual").lower())

            # Re-uploading as .pdf replaces the .txt variant (one file per doc).
            pdf_payload = b64.b64encode(b"%PDF-1.4 fake for storage test").decode()
            ok2, message2 = dashboard._save_reference_document(
                "ari_manual", "manual.pdf", "data:application/pdf;base64," + pdf_payload)
            self.assertTrue(ok2, message2)
            self.assertFalse(os.path.isfile(registered), "old .txt should be removed")
            stored = os.path.splitext(path)[0] + ".pdf"
            self.assertTrue(os.path.isfile(stored), message2)
        finally:
            references.REGISTRY_PATH = original_path
            references.ROOT_DIR = original_root
            stored = os.path.splitext(path)[0] + ".pdf"
            for candidate in (stored, path, tmp_reg):
                if os.path.exists(candidate):
                    os.remove(candidate)

    def test_save_reference_document_rejects_bad_type(self):
        ok, message = dashboard._save_reference_document(
            "ari_manual", "manual.exe", "data:application/octet-stream;base64,AAA=")
        self.assertFalse(ok)
        self.assertIn("Unsupported", message)


class TestLoadingStylesAreDicts(unittest.TestCase):
    """Regression: loading callbacks must return dict styles, not lists.

    A list-wrapped style ("[{'display': ...}]") crashes React's renderer
    ("indexed property on CSSStyleDeclaration") and the whole callback
    update is dropped, so responses never render in the browser.
    """

    def test_review_loading_returns_dict(self):
        style = dashboard.show_review_loading(1)
        self.assertIsInstance(style, dict)
        self.assertEqual(style.get("display"), "block")

    def test_prompt_loading_returns_dict(self):
        style = dashboard.show_prompt_loading(1, {"state": "connected"})
        self.assertIsInstance(style, dict)
        self.assertEqual(style.get("display"), "block")
        hidden = dashboard.show_prompt_loading(1, {"state": "untested"})
        self.assertIsInstance(hidden, dict)
        self.assertEqual(hidden.get("display"), "none")


def _walk_ids_list(components):
    """Walk a list/tuple of Dash components and yield their ids."""
    for component in components:
        yield from _walk_ids(component)


class TestFocusWritesInspectorStage(unittest.TestCase):
    """F1: pip_stage_focus must also emit store-inspector-stage."""

    def test_focus_returns_stage_in_both_stores(self):
        snaps = dashboard._stage_rows(None)
        # Any click on a stage card yields both outputs = the stage name.
        sel, insp, detail = dashboard.pip_stage_focus([1], None)
        self.assertEqual(sel, insp)
        self.assertIn(sel, dashboard.PIPELINE_STAGE_ORDER)
        self.assertIsInstance(detail, object)


class TestSavePersistsPrompts(unittest.TestCase):
    """F2 + Part 1: save writes prompts.json atomically with version bump."""

    def _backup(self):
        path = os.path.join(dashboard.BASE_DIR, "configs", "prompts.json")
        with open(path, encoding="utf-8") as f:
            self._orig = json.load(f)

    def _restore(self):
        path = os.path.join(dashboard.BASE_DIR, "configs", "prompts.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._orig, f, ensure_ascii=True, indent=2)

    def test_save_round_trip_and_references(self):
        path = os.path.join(dashboard.BASE_DIR, "configs", "prompts.json")
        self._backup()
        try:
            with open(path, encoding="utf-8") as f:
                before = json.load(f)
            key = "s3_citations"
            cfg = before["stages"][key]
            keys = sorted((cfg.get("prompts") or {}).keys())
            values = [cfg["prompts"][k] + " [edited]" for k in keys]
            v_before = cfg["version"]

            status, _cache = dashboard.canvas_inspector_save(
                1, "local", 0.25, 4200, "local", values, key, None)
            self.assertTrue(status.startswith("Saved."), status)

            with open(path, encoding="utf-8") as f:
                after = json.load(f)
            cfg2 = after["stages"][key]
            self.assertEqual(cfg2["version"], int(v_before) + 1)
            self.assertEqual(cfg2["temperature"], 0.25)
            self.assertEqual(cfg2["max_tokens"], 4200)
            self.assertEqual(cfg2.get("outlet"), "local")
            self.assertTrue(cfg2["prompts"][keys[0]].endswith(" [edited]"))
            # references field remains a list (Part 1 default keeps attachments)
            self.assertIsInstance(cfg2.get("references"), list)
        finally:
            self._restore()

    def test_save_rejects_unknown_outlet(self):
        path = os.path.join(dashboard.BASE_DIR, "configs", "prompts.json")
        self._backup()
        try:
            key = "s1_extract"
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)["stages"][key]
            keys = sorted(cfg["prompts"].keys())
            values = [cfg["prompts"][k] for k in keys]
            status, _ = dashboard.canvas_inspector_save(
                1, "local", 0.1, 2000, "no-such-outlet", values, key, None)
            self.assertIn("Invalid outlet", status)
        finally:
            self._restore()

    def test_save_rejects_empty_prompt(self):
        path = os.path.join(dashboard.BASE_DIR, "configs", "prompts.json")
        self._backup()
        try:
            with open(path, encoding="utf-8") as f:
                before = json.load(f)
            key = "s1_extract"
            cfg = before["stages"][key]
            keys = sorted(cfg["prompts"].keys())
            values = ["" for _ in keys]
            status, _ = dashboard.canvas_inspector_save(
                1, "local", 0.1, 2000, "", values, key, None)
            self.assertIn("must not be empty", status)
        finally:
            self._restore()


if __name__ == "__main__":
    unittest.main(verbosity=2)