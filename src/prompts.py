"""Prompt store loader for the Pubs Review Agent pipeline.

Goal 1: the boss must be able to see and edit the exact prompt text used at
every review node. The prompt store lives at configs/prompts.json (built from
the proven "Pubs Review Agent v3" AskSage workflow). This module loads it with
a hardcoded fallback so the app never breaks if the file is missing or corrupt.

ASCII/English only. Raises a warning (not an exception) on a missing or
corrupt file so the pipeline can still run on the fallback defaults.
"""

import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_PATH = os.path.join(BASE_DIR, "..", "configs", "prompts.json")


# ---------------------------------------------------------------------------
# Hardcoded fallback prompts (ASCII-only). These mirror the DAPAM_OCR source
# prompts for every stage so a missing configs/prompts.json never halts the
# pipeline. They are intentionally minimal but complete per stage.
# ---------------------------------------------------------------------------

_FALLBACK = {
    "s1_extract": {
        "model": "local", "temperature": 0.1, "max_tokens": 6000,
        "prompts": {
            "EXTRACT_PROMPT": (
                "You are a manuscript parsing specialist for APA journal "
                "submissions. Extract and structure the following manuscript.\n"
                "For EACH section, extract: section heading and APA heading "
                "level (1-5); VERBATIM in-text citations, statistical reports, "
                "acronyms with context; a 2-3 sentence prose summary; tables "
                "and figures referenced; estimated page range.\n"
                "Also extract METADATA: title, authors, affiliations, abstract "
                "with word count, keywords, totals (words, references, tables, "
                "figures), stated hypotheses, distribution statement, and any "
                "CUI/FOUO/classified markings.\n"
                "Also summarize the ARI PUBLICATION MANUAL rules and the Army "
                "AR/policy rules relevant to this manuscript.\n"
                "## LONG DOCUMENT HANDLING\nIf 50+ pages: summarize "
                "Introduction/Discussion/Literature Review; preserve VERBATIM "
                "Method/Results statistics and the reference list.\n"
                "## OUTPUT FORMAT\n===METADATA=== ... ===ARI_RULES=== ... "
                "===AR_RULES=== ... ===SECTION_n: [heading] (Level X)===\n"
                "Keep under 6000 tokens."
            ),
        },
    },
    "s2_cross_section": {
        "model": "local", "temperature": 0.1, "max_tokens": 4000,
        "prompts": {
            "CROSS_SECTION_PROMPT": (
                "You are a manuscript structure analyst. Based on the "
                "extracted manuscript, produce a cross-section inventory:\n"
                "- Every section with its APA heading level and page range\n"
                "- Every in-text citation mapped to a reference entry\n"
                "- Every statistical report with its context\n"
                "- Headings hierarchy and ordering\n"
                "Return a structured cross-section table. Keep under 4000 tokens."
            ),
        },
    },
    "s3_citations": {
        "model": "local", "temperature": 0.2, "max_tokens": 4000,
        "prompts": {
            "CITATIONS_ANALYSIS_PROMPT": (
                "You are a senior APA journal copy editor. Review for "
                "citations and APA 7th formatting.\n"
                "Check CITATIONS: every in-text citation has a matching "
                "reference and vice versa; et al. usage per APA 7th; DOI "
                "format; author name consistency; year accuracy.\n"
                "Check APA 7th FORMATTING: title page (no running head, title "
                "bold, author note); heading levels; abstract (150-250 words, "
                "keywords); seriation; table/figure formatting; number rules; "
                "block quotes; bias-free language per Chapter 5.\n"
                "## SEVERITY\nCRITICAL: missing/fabricated references, "
                "fundamental structure missing. MAJOR: systematic format "
                "errors. MODERATE: 3-5 errors. MINOR: spacing/font isolated.\n"
                "## OUTPUT\n| Page | Original Text | Issue | Correction | "
                "APA/ARI Source | Severity |\nSort by Severity.\n"
                "**OVERALL ASSESSMENT: [COMPLIANT / PARTIALLY_COMPLIANT / "
                "NON_COMPLIANT]**"
            ),
            "CITATIONS_COMPLIANT_PROMPT": (
                "Supportive citation/APA reviewer. COMPLIANT. Brief encouraging "
                "summary (under 500 tokens): 1) Acknowledge strong APA/ARI "
                "adherence. 2) Minor tweaks. 3) Recommendations. 4) Note overlap."
            ),
            "CITATIONS_PARTIALLY_PROMPT": (
                "Supportive citation/APA reviewer. PARTIALLY COMPLIANT. "
                "Prioritized remediation plan (under 800 tokens): 1) "
                "Acknowledge correct areas. 2) Major issues by severity. 3) "
                "Prioritized fixes. 4) Recommendations. 5) Note overlap."
            ),
            "CITATIONS_NON_COMPLIANT_PROMPT": (
                "Supportive but firm citation/APA reviewer. NON_COMPLIANT. "
                "Major overhaul plan (under 800 tokens): 1) Empathetic "
                "acknowledgment. 2) Fundamental issues. 3) Step-by-step "
                "overhaul. 4) Encouragement."
            ),
            "CITATIONS_FINAL_PROMPT": (
                "Final formatter for Citations & APA Review. Build the finding "
                "table from the analysis, sorted by severity with direct "
                "quotes, then the summary. Keep under 4000 tokens."
            ),
            "COMPLIANCE_EXTRACT_PROMPT": (
                "Extract overall compliance.\n\n"
                "Output ONLY one word: COMPLIANT / PARTIALLY_COMPLIANT / "
                "NON_COMPLIANT"
            ),
        },
    },
    "s4_sme": {
        "model": "local", "temperature": 0.3, "max_tokens": 4000,
        "prompts": {
            "SME_ANALYSIS_PROMPT": (
                "You are a subject-matter expert in the manuscript's domain. "
                "Review statistical analysis, methodology, and substantive "
                "claims for the target journal. Verify statistical reporting "
                "per APA 7th (effect sizes, confidence intervals), method "
                "soundness, and domain accuracy. Assign severities. "
                "**OVERALL ASSESSMENT: [COMPLIANT / PARTIALLY_COMPLIANT / "
                "NON_COMPLIANT]**"
            ),
            "SME_COMPLIANT_PROMPT": (
                "Supportive SME reviewer. COMPLIANT. Brief encouraging summary "
                "(under 500 tokens): acknowledge strong analysis, minor tweaks, "
                "recommendations, note overlap."
            ),
            "SME_PARTIALLY_PROMPT": (
                "Supportive SME reviewer. PARTIALLY COMPLIANT. Prioritized "
                "remediation (under 800 tokens): correct areas, issues by "
                "severity, fixes, recommendations, note overlap."
            ),
            "SME_NON_COMPLIANT_PROMPT": (
                "Supportive but firm SME reviewer. NON_COMPLIANT. Overhaul plan "
                "(under 800 tokens): empathy, fundamental issues, step-by-step "
                "overhaul, encouragement."
            ),
            "SME_FINAL_PROMPT": (
                "Final formatter for SME + Statistics Review. Build the finding "
                "table sorted by severity with direct quotes, then the summary."
            ),
            "COMPLIANCE_EXTRACT_PROMPT": (
                "Extract overall compliance. Output ONLY one word: COMPLIANT / "
                "PARTIALLY_COMPLIANT / NON_COMPLIANT"
            ),
        },
    },
    "s5_copyedit": {
        "model": "local", "temperature": 0.1, "max_tokens": 4000,
        "prompts": {
            "COPYEDIT_ANALYSIS_PROMPT": (
                "You are a senior copy editor. Review grammar, style, clarity, "
                "bias-free language (APA 7th Chapter 5), and originality/plagiarism "
                "flags. Assign severities. **OVERALL ASSESSMENT: [COMPLIANT / "
                "PARTIALLY_COMPLIANT / NON_COMPLIANT]**"
            ),
            "COPYEDIT_COMPLIANT_PROMPT": (
                "Supportive copy editor. COMPLIANT. Brief encouraging summary "
                "(under 500 tokens)."
            ),
            "COPYEDIT_PARTIALLY_PROMPT": (
                "Supportive copy editor. PARTIALLY COMPLIANT. Prioritized "
                "remediation (under 800 tokens)."
            ),
            "COPYEDIT_NON_COMPLIANT_PROMPT": (
                "Supportive but firm copy editor. NON_COMPLIANT. Overhaul plan "
                "(under 800 tokens)."
            ),
            "COPYEDIT_FINAL_PROMPT": (
                "Final formatter for CopyEdit + Bias + Originality Review. "
                "Build the finding table sorted by severity, then the summary."
            ),
            "COMPLIANCE_EXTRACT_PROMPT": (
                "Extract overall compliance. Output ONLY one word: COMPLIANT / "
                "PARTIALLY_COMPLIANT / NON_COMPLIANT"
            ),
        },
    },
    "s6_dedup": {
        "model": "local", "temperature": 0.0, "max_tokens": 4000,
        "prompts": {
            "DEDUP_PROMPT": (
                "You are a review consolidator. Merge the findings from the "
                "citations, SME, and copyedit passes, removing duplicates "
                "(same page + issue) and keeping the highest severity. Produce "
                "a single deduplicated, severity-sorted finding list. Keep "
                "under 4000 tokens."
            ),
        },
    },
    "s7_report": {
        "model": "local", "temperature": 0.3, "max_tokens": 4000,
        "prompts": {
            "REPORT_PROMPT": (
                "You are the final editorial report generator. Given the "
                "deduplicated findings, produce the final report: an editor "
                "memo and/or author letter per the requested output mode, with "
                "a severity summary table and the consolidated recommendations."
            ),
            "AUTHOR_LETTER_PROMPT": (
                "Write a supportive author letter summarizing the review: "
                "acknowledge strengths, list required revisions by severity, "
                "and close encouragingly."
            ),
            "EDITOR_MEMO_PROMPT": (
                "Write an editor memo summarizing the review decision, "
                "compliance verdicts per domain, severity table, and "
                "recommended action."
            ),
        },
    },
}


def _load_json(path):
    """Read and parse a UTF-8 JSON file; return (data, error)."""
    if not os.path.isfile(path):
        return None, "missing"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def find_stage_config(store, stage):
    """Return the per-stage config dict, or None if missing/malformed."""
    if not isinstance(store, dict):
        return None
    stages = store.get("stages")
    if not isinstance(stages, dict):
        return None
    cfg = stages.get(stage)
    if not isinstance(cfg, dict):
        return None
    return cfg


def get_prompt(store, stage, prompt_key):
    """Return the prompt text for (stage, prompt_key) if present, else None."""
    cfg = find_stage_config(store, stage)
    if cfg is None:
        return None
    prompts = cfg.get("prompts")
    if not isinstance(prompts, dict):
        return None
    val = prompts.get(prompt_key)
    return val if isinstance(val, str) and val.strip() else None


def local_store_path():
    return PROMPTS_PATH


def load_store(path=PROMPTS_PATH, warn=True):
    """Load the prompt store, falling back to hardcoded defaults.

    Returns (store, warning). warning is a non-empty string when the file is
    missing/corrupt (in which case the fallback is returned) or "" on success.
    """
    data, err = _load_json(path)
    if err is None:
        return data, ""
    if warn:
        print("prompt store %s; using hardcoded fallback: %s" % (
            "missing" if err == "missing" else "corrupt", err))
    fallback_data = {"schema_version": 1, "stages": _FALLBACK,
                     "_source": "hardcoded-fallback"}
    return fallback_data, err or "fallback"


def stage_summary(store, stage):
    """Human-readable summary of a stage's config: model, temp, version."""
    cfg = find_stage_config(store, stage)
    if cfg is None:
        return "stage %s: no config" % stage
    ver = cfg.get("version", "?")
    temp = cfg.get("temperature", "?")
    model = cfg.get("model", "?")
    return "%s | temp %s | prompt v%s | %d prompt(s)" % (
        model, temp, ver, len(cfg.get("prompts", {})))


def normalize_stage_name(stage):
    """Map the real S1-S7 names to their stage keys (accept both forms)."""
    aliases = {
        "s1": "s1_extract", "s1_extract": "s1_extract", "extract": "s1_extract",
        "extract_parse": "s1_extract",
        "s2": "s2_cross_section", "s2_cross_section": "s2_cross_section",
        "cross_section": "s2_cross_section",
        "s3": "s3_citations", "s3_citations": "s3_citations",
        "citations": "s3_citations", "apa": "s3_citations",
        "s4": "s4_sme", "s4_sme": "s4_sme", "sme": "s4_sme",
        "s5": "s5_copyedit", "s5_copyedit": "s5_copyedit", "copyedit": "s5_copyedit",
        "s6": "s6_dedup", "s6_dedup": "s6_dedup", "dedup": "s6_dedup",
        "s7": "s7_report", "s7_report": "s7_report", "report": "s7_report",
    }
    key = (stage or "").strip().lower()
    return aliases.get(key, stage)
