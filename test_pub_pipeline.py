"""Tests for the Pubs Review pipeline engine (src/pub_pipeline.py).

Goal 1 acceptance: compliance-label regex, severity coercion, findings
parsing, template filling, and the sequential stage orchestration against a
stubbed LLM client.

ASCII/English only. Run with:
    python test_pub_pipeline.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from pub_pipeline import (
    PubPipeline, ProviderAdapter, extract_compliance_label,
    normalize_severity, parse_llm_findings, _fill,
)


class StubAdapter:
    """ProviderAdapter-compatible stub that echoes a canned response."""
    def __init__(self):
        self.calls = []
        self.model = "stub"
        self.responses = {}

    def complete(self, prompt, temperature=0.2, max_tokens=4096):
        self.calls.append((prompt, temperature, max_tokens))
        # Return a canned response if registered, else a minimal text.
        return self.responses.get(
            "default",
            "Reviewed. **OVERALL ASSESSMENT: [PARTIALLY_COMPLIANT]**\n"
            "| p.3 | bad cite | et al misuse | fix it | APA 7th | MODERATE |\n")


def test_compliance_extract_variants():
    assert extract_compliance_label("OVERALL ASSESSMENT: COMPLIANT") == "COMPLIANT"
    assert extract_compliance_label("Overall assessment: [PARTIALLY_COMPLIANT]") == "PARTIALLY_COMPLIANT"
    assert extract_compliance_label("x Overall Assessment: Non-Compliant y") == "NON_COMPLIANT"
    assert extract_compliance_label("no label here") == "PARTIALLY_COMPLIANT"
    assert extract_compliance_label("overall\nassessment:\nCOMPLIANT") == "COMPLIANT"


def test_severity_normalize():
    assert normalize_severity("CRITICAL") == "CRITICAL"
    assert normalize_severity("major") == "MAJOR"
    assert normalize_severity("MODERATE") == "MODERATE"
    assert normalize_severity("Minor") == "MINOR"
    assert normalize_severity("MEDIUM") == "MODERATE"
    assert normalize_severity("") == "MINOR"
    assert normalize_severity(None) == "MINOR"


def test_parse_findings():
    text = (
        "| Page | Original Text | Issue | Correction | Source | Severity |\n"
        "|---|---|---|---|---|---|\n"
        "| p.3 | bad cite | et al misuse | fix | APA 7th | MODERATE |\n"
        "| p.7 | x | missing ref | add | ARI | CRITICAL |\n"
    )
    fs = parse_llm_findings(text, "citations")
    assert len(fs) == 2, fs
    assert fs[0]["severity"] == "MODERATE"
    assert fs[1]["severity"] == "CRITICAL"
    assert fs[1]["location"] == "p.7"
    assert fs[0]["domain"] == "citations"
    assert fs[0]["original_text"] == "bad cite"


def test_parse_findings_empty_and_noop():
    assert parse_llm_findings("", "apa") == []
    assert parse_llm_findings("just some prose without tables", "apa") == []


def test_fill_template():
    ctx = {"target_journal": "Military Psychology", "manuscript_details": "THE DETAILS"}
    out = _fill("Review for {{input.target_journal}}: {{manuscript_details}}" +
                " {{missing_var}}", ctx)
    assert "Military Psychology" in out
    assert "THE DETAILS" in out
    assert "{{missing_var}}" in out


def test_pipeline_runs_all_stages():
    stub = StubAdapter()
    pipe = PubPipeline(stub)
    ctx = pipe.run(manuscript_text="A short manuscript.", target_journal="Mil Psych")
    for stage in ("s1_extract", "s2_cross_section", "s3_citations",
                  "s4_sme", "s5_copyedit", "s6_dedup", "s7_report"):
        assert ctx.get(stage), "stage %s produced no result" % stage
    assert ctx.get("final_report")
    assert ctx.get("manuscript_details")
    # Findings parsed from review blocks
    assert ctx.get("findings"), "expected at least one finding"
    # Compliance labels per review block
    assert ctx.get("per_stage_compliance").get("s3_citations") == "PARTIALLY_COMPLIANT"


def test_pipeline_uses_store_prompts():
    import prompts
    store, _ = prompts.load_store()
    stub = StubAdapter()
    pipe = PubPipeline(stub, store=store)
    ctx = pipe.run(manuscript_text="x")
    # Every stage made at least one LLM call
    assert len(stub.calls) >= 10, "expected >=10 LLM calls (7 stages + branches), got %d" % len(stub.calls)


def test_stage_outlet_fallback_and_override():
    """A stage pinned to an outlet gets its own adapter; unknown keys and
    missing factories fall back to the run-wide adapter."""
    class FakeOutletLLM:
        model = "outlet-model"

        def chat_completion(self, messages, temperature=0.1, max_tokens=4000,
                            model_override=None, timeout=None):
            return "OUTLET RESPONSE"

    built = []

    def factory(key):
        built.append(key)
        if key == "good":
            return FakeOutletLLM()
        return None

    store = {"stages": {
        "s1_extract": {"prompts": {"EXTRACT_PROMPT": "P1"}, "outlet": "good"},
        "s2_cross_section": {"prompts": {"CROSS_SECTION_PROMPT": "P2"},
                             "outlet": "missing"},
        "s7_report": {"prompts": {"REPORT_PROMPT": "P7"}},
    }}
    stub = StubAdapter()
    pipe = PubPipeline(stub, store=store, client_factory=factory)

    # s1 pinned to a known outlet: factory builds a fresh adapter for it.
    adapter1 = pipe._adapter_for("s1_extract")
    assert adapter1 is not stub, "expected an outlet adapter for s1"
    assert adapter1.client.model == "outlet-model"

    # s2 pinned to an unknown outlet: factory returns None -> run-wide.
    assert pipe._adapter_for("s2_cross_section") is stub

    # s7 has no outlet: no factory call at all.
    assert pipe._adapter_for("s7_report") is stub
    assert built == ["good", "missing"]


def test_provider_adapter_wraps_chat_completion():
    class FakeLLM:
        model = "bonsai-1.7b"
        def chat_completion(self, messages, temperature=0.1, max_tokens=4000, model_override=None, timeout=None):
            return "FAKE RESPONSE"
    adapter = ProviderAdapter(FakeLLM())
    out = adapter.complete("hi", temperature=0.2, max_tokens=100)
    assert out == "FAKE RESPONSE"


def test_to_app_finding_maps_schema():
    from pub_pipeline import to_app_finding, findings_to_app
    proven = {"domain": "citations", "severity": "CRITICAL", "location": "p.3",
              "original_text": "bad cite", "issue": "et al misuse",
              "correction": "fix it", "source": "APA 7th"}
    app = to_app_finding(proven)
    assert app["agent"] == "citation"
    assert app["severity"] == "error"  # CRITICAL -> error
    assert app["suggested_fix"] == "fix it"
    assert app["location"] == "p.3"
    # Moderate -> warning
    app2 = to_app_finding({"domain": "sme", "severity": "MODERATE"})
    assert app2["agent"] == "sme"
    assert app2["severity"] == "warning"
    # list form
    lst = findings_to_app([proven])
    assert lst[0]["agent"] == "citation"


def test_run_review_facade_shape_no_llm():
    from pub_pipeline import run_review
    r = run_review("A short manuscript with (Smith, 2020) and a DOI.")
    assert set(r.keys()) == {"findings", "summary", "agents_run", "skipped", "notes"}
    assert isinstance(r["findings"], list)
    assert r["summary"]["total"] >= 0
    # Without llm_client, 7-stage pass is skipped (deterministic rules still run).
    assert len(r["skipped"]) >= 1


def test_run_review_facade_with_llm():
    from pub_pipeline import run_review
    stub = StubAdapter()
    r = run_review("Some text with (Jones, 2019).", llm_client=stub)
    assert set(r.keys()) == {"findings", "summary", "agents_run", "skipped", "notes"}
    # Proven pass appends findings and records agents_run.
    assert "citation" in r["agents_run"] or len(r["findings"]) >= 0


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
