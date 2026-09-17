"""
Test script for the review engine (src/review_agents.py, src/summary_letter.py).

Plain-Python test script (no pytest). Run with:
    .\.venv\Scripts\python.exe test_review_agents.py

ASCII only, English only, no emoji.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from review_agents import run_review, make_finding, FINDING_KEYS  # noqa: E402
from summary_letter import build_summary_letter  # noqa: E402

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    """Print a PASS/FAIL line and update the counters."""
    global PASS, FAIL
    if condition:
        PASS += 1
        print("PASS: {}".format(name))
    else:
        FAIL += 1
        print("FAIL: {} {}".format(name, detail))


# ---------------------------------------------------------------------------
# Fixture manuscript with deliberately planted errors.
# ---------------------------------------------------------------------------
FIXTURE = """\
Research Plan for Automated Review Tools

This study examines how automation affects manuscript quality. According to
(Smith and Jones, 2020), the impact is significant. Another source notes that
the effect persists (Brown, n.d.) and a third finding is reported without a
year at all (Taylor, 2021).

Earlier work reached a similar conclusion (Doe, 2019). See also the discussion
in (Johnson et al., 2018). Some authors still rely on ibid. to shorten notes.
An undated reference appears as (Lee, no date).

Methodology and Design Approach

figure 1 shows the workflow. There were fifteen participants in the sample.
The findings are summarized in Table 2. below.

References
Doe, J. (2019). Automated review systems. Journal of Automation, 12(3), 45-60.
Smith, A., & Jones, B. (2020). Review quality. Journal of Methods, 8(2), 10-20.
Lee, C. Automated systems without a year. Journal of Tools, 4(1), 5-8.
"""


class FakeLLM:
    """A fake LLM client whose chat_completion returns a canned JSON array."""

    def __init__(self, response):
        self.response = response

    def chat_completion(self, messages, temperature=0.1, max_tokens=4000):
        return self.response


class BadLLM:
    """A fake LLM client whose chat_completion returns non-JSON text."""

    def chat_completion(self, messages, temperature=0.1, max_tokens=4000):
        return "not json"


def test_schema_helpers():
    """FINDING_KEYS order and make_finding validation."""
    expected = ["agent", "severity", "location", "original_text", "issue", "suggested_fix", "source"]
    check("FINDING_KEYS order", FINDING_KEYS == expected, str(FINDING_KEYS))

    f = make_finding("citation", "error", "line 1", "x", "y", "z", "s")
    check("make_finding returns dict with exact keys",
          list(f.keys()) == expected, str(list(f.keys())))

    try:
        make_finding("citation", "bogus", "line 1", "x", "y", "z", "s")
        check("make_finding rejects unknown severity", False, "no exception raised")
    except ValueError:
        check("make_finding rejects unknown severity", True)


def test_deterministic_rules():
    """Run run_review with llm_client=None and assert planted errors appear."""
    result = run_review(FIXTURE, llm_client=None)
    findings = result["findings"]

    def has(agent, severity, substring):
        for f in findings:
            if f["agent"] == agent and f["severity"] == severity \
                    and substring.lower() in f["issue"].lower():
                return f
        return None

    f = has("citation", "error", "and")
    check("parenthetical 'and' instead of '&' flagged as error",
          f is not None, "not found")

    f = has("citation", "error", "missing a year")
    check("citation missing a year flagged as error",
          f is not None, "not found")

    f = has("citation", "error", "ibid")
    check("ibid. usage flagged as error",
          f is not None, "not found")

    f = has("citation", "warning", "alphabetical")
    check("out-of-alphabetical-order reference flagged as warning",
          f is not None, "not found")

    f = has("citation", "warning", "no year")
    check("reference entry missing a year flagged as warning",
          f is not None, "not found")

    f = has("apa", "warning", "sentence case")
    check("Title Case heading flagged as warning",
          f is not None, "not found")

    f = has("apa", "warning", "lowercase")
    check("lowercase figure label flagged as warning",
          f is not None, "not found")

    f = has("apa", "warning", "numeral")
    check("numeral rule violation flagged as warning",
          f is not None, "not found")

    # Summary counts should reflect the findings present.
    check("summary total matches findings count",
          result["summary"]["total"] == len(findings),
          "{} vs {}".format(result["summary"]["total"], len(findings)))


def test_llm_merge_and_parse_failure():
    """Fake LLM findings are parsed/merged; malformed response yields zero + note."""
    canned = [
        {
            "agent": "apa",
            "severity": "warning",
            "location": "line 99",
            "original_text": "some text",
            "issue": "LLM found a style issue",
            "suggested_fix": "fix it",
            "source": "APA 7 section 2.1",
        }
    ]
    fake = FakeLLM(json_dumps(canned))
    result = run_review(FIXTURE, llm_client=fake)
    merged = [f for f in result["findings"] if f["issue"] == "LLM found a style issue"]
    check("fake LLM finding parsed and merged", len(merged) == 1,
          "found {}".format(len(merged)))

    bad = BadLLM()
    result2 = run_review(FIXTURE, llm_client=bad)
    any_parse_note = any("parse_failure" in n for n in result2["notes"])
    check("malformed LLM response yields parse_failure note",
          any_parse_note, str(result2["notes"]))
    check("malformed LLM response raises no exception", True)


def test_dedup():
    """A fake LLM finding identical to a rule finding is not double-counted."""
    # Find a rule finding we can mirror.
    base = run_review(FIXTURE, llm_client=None)
    rule_finding = None
    for f in base["findings"]:
        if f["agent"] == "apa" and f["severity"] == "warning":
            rule_finding = f
            break
    if rule_finding is None:
        check("found a rule finding to mirror for dedup", False, "none available")
        return

    fake = FakeLLM(json_dumps([rule_finding]))
    result = run_review(FIXTURE, llm_client=fake)
    # Count how many findings match the rule finding's issue.
    count = sum(1 for f in result["findings"]
                if f["issue"].lower() == rule_finding["issue"].lower()
                and f["location"].lower() == rule_finding["location"].lower())
    check("identical LLM finding is deduplicated (count == 1)",
          count == 1, "count = {}".format(count))


def test_summary_letter():
    """build_summary_letter returns non-empty Markdown containing counts."""
    result = run_review(FIXTURE, llm_client=None)
    letter = build_summary_letter("Fixture.docx", result, "Bonsai-1.7B (local)")
    check("summary letter is non-empty", bool(letter.strip()))
    total = result["summary"]["total"]
    check("summary letter contains the total count",
          str(total) in letter, letter[:200])
    check("summary letter mentions human verification",
          "human verification" in letter)
    check("summary letter is ASCII",
          all(ord(ch) < 128 for ch in letter), "non-ASCII found")


def json_dumps(obj):
    import json
    return json.dumps(obj)


def main():
    print("Review Engine Test Suite")
    print("=" * 50)
    test_schema_helpers()
    test_deterministic_rules()
    test_llm_merge_and_parse_failure()
    test_dedup()
    test_summary_letter()
    print("=" * 50)
    print("SUMMARY: {} PASS, {} FAIL".format(PASS, FAIL))
    if FAIL == 0:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
