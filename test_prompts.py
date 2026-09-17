"""Tests for the prompt store loader (src/prompts.py).

Goal 1 acceptance: prompt store loads from configs/prompts.json, falls back
to hardcoded defaults on missing/corrupt file, is ASCII-clean, and exposes
per-stage config summary.

ASCII/English only. Run with:
    python test_prompts.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import prompts


def test_load_from_file():
    store, warn = prompts.load_store()
    assert warn == "", "expected no warning on valid store, got %r" % warn
    assert store.get("schema_version") == 1
    assert len(store["stages"]) == 7, "expected 7 stages"


def test_stage_presence():
    store, _ = prompts.load_store()
    for stage in ("s1_extract", "s2_cross_section", "s3_citations",
                  "s4_sme", "s5_copyedit", "s6_dedup", "s7_report"):
        assert prompts.find_stage_config(store, stage) is not None, stage


def test_s3_has_all_prompt_keys():
    store, _ = prompts.load_store()
    s3 = store["stages"]["s3_citations"]["prompts"]
    for key in ("CITATIONS_ANALYSIS_PROMPT", "CITATIONS_COMPLIANT_PROMPT",
                "CITATIONS_PARTIALLY_PROMPT", "CITATIONS_NON_COMPLIANT_PROMPT",
                "CITATIONS_FINAL_PROMPT", "COMPLIANCE_EXTRACT_PROMPT"):
        assert key in s3, key


def test_prompts_are_nonempty_strings():
    store, _ = prompts.load_store()
    for stage, cfg in store["stages"].items():
        for key, val in cfg["prompts"].items():
            assert isinstance(val, str) and val.strip(), (stage, key)


def test_ascii_only():
    store, _ = prompts.load_store()
    raw = json.dumps(store, ensure_ascii=False)
    bad = sorted({c for c in raw if ord(c) > 127})
    assert bad == [], "non-ascii chars: %r" % bad


def test_missing_file_fallback():
    p = os.path.join(tempfile.gettempdir(), "definitely_missing_prompts.json")
    if os.path.exists(p):
        os.remove(p)
    store, warn = prompts.load_store(p)
    assert warn, "expected a warning for missing file"
    assert store.get("_source") == "hardcoded-fallback"
    # Fallback still has all 7 stages
    assert len(store["stages"]) == 7


def test_corrupt_file_fallback():
    p = os.path.join(tempfile.gettempdir(), "corrupt_prompts.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ not valid json")
    store, warn = prompts.load_store(p)
    assert warn, "expected a warning for corrupt file"
    assert store.get("_source") == "hardcoded-fallback"


def test_get_prompt_missing_key_returns_none():
    store, _ = prompts.load_store()
    assert prompts.get_prompt(store, "s3_citations", "NOT_A_REAL_KEY") is None
    assert prompts.get_prompt(store, "no_such_stage", "CITATIONS_ANALYSIS_PROMPT") is None


def test_normalize_stage_name():
    assert prompts.normalize_stage_name("apa") == "s3_citations"
    assert prompts.normalize_stage_name("S3") == "s3_citations"
    assert prompts.normalize_stage_name("sme") == "s4_sme"
    assert prompts.normalize_stage_name("s1_extract") == "s1_extract"


def test_stage_summary_nonempty():
    store, _ = prompts.load_store()
    for stage in store["stages"]:
        s = prompts.stage_summary(store, stage)
        assert isinstance(s, str) and s.strip(), stage


def test_version_and_timestamp_present():
    store, _ = prompts.load_store()
    for stage, cfg in store["stages"].items():
        assert cfg.get("version", 0) >= 1, stage
        assert cfg.get("updated_at"), stage


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            failed += 1
            print("FAIL %s: %s" % (t.__name__, e))
        except Exception as e:
            failed += 1
            print("ERROR %s: %s" % (t.__name__, e))
    print("SUMMARY: %d PASS, %d FAIL" % (passed, failed))
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
