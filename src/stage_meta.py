"""Stage metadata: display names, badges, and the sub-step flow manifest.

The single source of truth for how the 7 review stages are presented and how
their internal sub-steps (the "flow" the boss asked to see) are rendered in
the accordion. Each stage maps to its prompts.json key; stages 3/4/5 carry a
4-step flow:

    Analyze -> Compliance label -> Branch (3-way) -> Final format

The branch step is a group of three alternatives; only one runs, chosen by the
compliance label produced in the previous step.

ASCII/English only. No imports beyond the standard library; prompts.json keys
are referenced by name and must exist for 'tests/test_stage_meta.py' checks.
"""

#: Ordered list of the 7 stages: (key, display title, badge).
STAGES = [
    ("s1_extract", "Extract & Parse", "IO"),
    ("s2_cross_section", "Cross-Section Analysis", "STEP"),
    ("s3_citations", "Citations & APA Review", "LLM"),
    ("s4_sme", "SME + Statistics Review", "LLM"),
    ("s5_copyedit", "CopyEdit + Bias + Originality", "LLM"),
    ("s6_dedup", "Dedup & Consolidate", "STEP"),
    ("s7_report", "Final Report", "STEP"),
]

#: Display titles by key.
STAGE_TITLES = {key: title for key, title, _ in STAGES}

#: Badges by key.
STAGE_BADGES = {key: badge for key, _, badge in STAGES}

#: Canonical order of stage keys.
STAGE_ORDER = [key for key, _, _ in STAGES]

#: The three gated LLM review stages (behind the approval gate).
GATED_STAGES = ["s3_citations", "s4_sme", "s5_copyedit"]

#: Sub-step definitions per stage.
#: A sub-step is a dict: {"label": str, "kind": "single"|"group",
#:                       "prompt_keys": [..]}.
#: kind "single" -> one prompt key; kind "group" -> alternatives (branch).
SUB_STEPS = {
    "s1_extract": [
        {"label": "Parse manuscript", "kind": "single", "prompt_keys": ["EXTRACT_PROMPT"]},
    ],
    "s2_cross_section": [
        {"label": "Cross-section analysis", "kind": "single", "prompt_keys": ["CROSS_SECTION_PROMPT"]},
    ],
    "s3_citations": [
        {"label": "Analyze", "kind": "single", "prompt_keys": ["CITATIONS_ANALYSIS_PROMPT"]},
        {"label": "Compliance label", "kind": "single", "prompt_keys": ["COMPLIANCE_EXTRACT_PROMPT"]},
        {"label": "Branch response", "kind": "group", "prompt_keys": [
            "CITATIONS_COMPLIANT_PROMPT", "CITATIONS_PARTIALLY_PROMPT", "CITATIONS_NON_COMPLIANT_PROMPT"]},
        {"label": "Final format", "kind": "single", "prompt_keys": ["CITATIONS_FINAL_PROMPT"]},
    ],
    "s4_sme": [
        {"label": "Analyze", "kind": "single", "prompt_keys": ["SME_ANALYSIS_PROMPT"]},
        {"label": "Compliance label", "kind": "single", "prompt_keys": ["COMPLIANCE_EXTRACT_PROMPT"]},
        {"label": "Branch response", "kind": "group", "prompt_keys": [
            "SME_COMPLIANT_PROMPT", "SME_PARTIALLY_PROMPT", "SME_NON_COMPLIANT_PROMPT"]},
        {"label": "Final format", "kind": "single", "prompt_keys": ["SME_FINAL_PROMPT"]},
    ],
    "s5_copyedit": [
        {"label": "Analyze", "kind": "single", "prompt_keys": ["COPYEDIT_ANALYSIS_PROMPT"]},
        {"label": "Compliance label", "kind": "single", "prompt_keys": ["COMPLIANCE_EXTRACT_PROMPT"]},
        {"label": "Branch response", "kind": "group", "prompt_keys": [
            "COPYEDIT_COMPLIANT_PROMPT", "COPYEDIT_PARTIALLY_PROMPT", "COPYEDIT_NON_COMPLIANT_PROMPT"]},
        {"label": "Final format", "kind": "single", "prompt_keys": ["COPYEDIT_FINAL_PROMPT"]},
    ],
    "s6_dedup": [
        {"label": "Consolidate findings", "kind": "single", "prompt_keys": ["DEDUP_PROMPT"]},
    ],
    "s7_report": [
        {"label": "Generate editorial report", "kind": "single", "prompt_keys": ["REPORT_PROMPT"]},
    ],
}

#: Default reference-document attachments per stage (keys into references.json).
#: S1 takes everything (like the original Extract node's file_variables); the
#: three review stages get the docs most relevant to their domain. Editable in
#: the UI; these are the seeded values.
DEFAULT_REFERENCES = {
    "s1_extract": ["ari_manual", "army_ar_rag", "dtic_regs"],
    "s2_cross_section": [],
    "s3_citations": ["ari_manual", "dtic_regs"],
    "s4_sme": ["army_ar_rag", "ari_manual"],
    "s5_copyedit": ["dtic_regs", "army_ar_rag"],
    "s6_dedup": [],
    "s7_report": [],
}

#: Default model selector per stage ("local" = Maple, "custom" = API outlet).
DEFAULT_MODEL = {key: "local" for key in STAGE_ORDER}


def stage_title(key):
    return STAGE_TITLES.get(key, key)


def stage_badge(key):
    return STAGE_BADGES.get(key, "STEP")


def sub_steps(key):
    """Return the sub-step list for a stage (empty for unknown keys)."""
    return SUB_STEPS.get(key, [])


def all_prompt_keys_for_stage(key):
    """Flatten every prompt key referenced by the stage's sub-steps."""
    out = []
    for step in SUB_STEPS.get(key, []):
        out.extend(step.get("prompt_keys", []))
    return out