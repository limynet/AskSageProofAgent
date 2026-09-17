"""Build configs/prompts.json from the proven DAPAM_OCR prompt modules.

Goal 1 task: import the proven "Pubs Review Agent v3" prompts (extracted
verbatim from the 43-node AskSage workflow) into an editable, versioned
prompt store that the Dash app reads and the boss can edit in the UI.

ASCII/English only: no emoji, no em-dashes, no non-ASCII.

Usage:
    python tools/build_prompts_json.py --source C:/Users/haiji/Documents/DAPAM_OCR
    python tools/build_prompts_json.py --out configs/prompts.json
"""

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone


# Proven stage temperatures (from DAPAM_OCR/pubs_review/pipeline.py STAGE_CONFIG)
STAGE_TEMPLATE = {
    "s1_extract": {
        "model": "local",
        "temperature": 0.1,
        "max_tokens": 6000,
        "handles_chunking": False,
        "prompts": {},
    },
    "s2_cross_section": {
        "model": "local",
        "temperature": 0.1,
        "max_tokens": 4000,
        "handles_chunking": False,
        "prompts": {},
    },
    "s3_citations": {
        "model": "local",
        "temperature": 0.2,
        "max_tokens": 4000,
        "handles_chunking": False,
        "prompts": {},
    },
    "s4_sme": {
        "model": "local",
        "temperature": 0.3,
        "max_tokens": 4000,
        "handles_chunking": False,
        "prompts": {},
    },
    "s5_copyedit": {
        "model": "local",
        "temperature": 0.1,
        "max_tokens": 4000,
        "handles_chunking": False,
        "prompts": {},
    },
    "s6_dedup": {
        "model": "local",
        "temperature": 0.0,
        "max_tokens": 4000,
        "handles_chunking": False,
        "prompts": {},
    },
    "s7_report": {
        "model": "local",
        "temperature": 0.3,
        "max_tokens": 4000,
        "handles_chunking": False,
        "prompts": {},
    },
}

# module name -> list of prompt constants to import
MODULE_PROMPTS = {
    "extract": ["EXTRACT_PROMPT", "ARI_RULES_PROMPT", "AR_RULES_PROMPT"],
    "cross_section": ["CROSS_SECTION_PROMPT"],
    "citations": [
        "CITATIONS_ANALYSIS_PROMPT",
        "CITATIONS_COMPLIANT_PROMPT",
        "CITATIONS_PARTIALLY_PROMPT",
        "CITATIONS_NON_COMPLIANT_PROMPT",
        "CITATIONS_FINAL_PROMPT",
        "COMPLIANCE_EXTRACT_PROMPT",
    ],
    "sme": [
        "SME_ANALYSIS_PROMPT",
        "SME_COMPLIANT_PROMPT",
        "SME_PARTIALLY_PROMPT",
        "SME_NON_COMPLIANT_PROMPT",
        "SME_FINAL_PROMPT",
        "COMPLIANCE_EXTRACT_PROMPT",
    ],
    "copyedit": [
        "COPYEDIT_ANALYSIS_PROMPT",
        "COPYEDIT_COMPLIANT_PROMPT",
        "COPYEDIT_PARTIALLY_PROMPT",
        "COPYEDIT_NON_COMPLIANT_PROMPT",
        "COPYEDIT_FINAL_PROMPT",
        "COMPLIANCE_EXTRACT_PROMPT",
    ],
    "dedup": ["DEDUP_PROMPT"],
    "report": ["REPORT_PROMPT", "AUTHOR_LETTER_PROMPT", "EDITOR_MEMO_PROMPT"],
}

STAGE_BY_MODULE = {
    "extract": "s1_extract",
    "cross_section": "s2_cross_section",
    "citations": "s3_citations",
    "sme": "s4_sme",
    "copyedit": "s5_copyedit",
    "dedup": "s6_dedup",
    "report": "s7_report",
}


def load_module(name, source_dir):
    path = os.path.join(source_dir, "pubs_review", "prompts", name + ".py")
    spec = importlib.util.spec_from_file_location("dapam_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_prompts_module(name):
    """Create the base prompt module (extract/cross_section/dedup/report) if a
    shared base of prompt constants exists in a sibling module; else None."""
    return None


def _ascii_sanitize(text):
    """Replace the only known non-ASCII characters (em-dash, en-dash) with
    ASCII hyphens so the store is ASCII-clean. Any other non-ASCII fails."""
    return (text
            .replace("\u2014", "-")
            .replace("\u2013", "-")
            .replace("\u2019", "'")
            .replace("\u2018", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"'))


def collect(source_dir):
    store = {}
    for module_name, const_names in MODULE_PROMPTS.items():
        mod = load_module(module_name, source_dir)
        stage = STAGE_BY_MODULE[module_name]
        prompts = STAGE_TEMPLATE[stage]["prompts"]
        missing = []
        for cname in const_names:
            if hasattr(mod, cname):
                val = getattr(mod, cname)
                prompts[cname] = _ascii_sanitize(val) if isinstance(val, str) else val
            else:
                missing.append(cname)
        # Trim unused keys for missing constants (dedup/report may have fewer)
        store[stage] = {
            "model": STAGE_TEMPLATE[stage]["model"],
            "temperature": STAGE_TEMPLATE[stage]["temperature"],
            "max_tokens": STAGE_TEMPLATE[stage]["max_tokens"],
            "handles_chunking": STAGE_TEMPLATE[stage]["handles_chunking"],
            "prompts": prompts,
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": "Imported verbatim from Pubs Review Agent v3 (DAPAM_OCR). Check missing: " + ",".join(missing) if missing else "",
        }
    return store


def check_ascii(store):
    bad = {}
    for stage, cfg in store.items():
        for key, text in cfg["prompts"].items():
            if isinstance(text, str):
                for ch in text:
                    if ord(ch) > 127:
                        bad.setdefault(stage + "/" + key, []).append(
                            "U+%04X %s" % (ord(ch), ch)
                        )
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=r"C:\Users\haiji\Documents\DAPAM_OCR")
    ap.add_argument("--out", default=r"C:\Users\haiji\Documents\AskSageProofAgent_Local\configs\prompts.json")
    args = ap.parse_args()

    if not os.path.isdir(os.path.join(args.source, "pubs_review")):
        print("ERROR: source dir missing pubs_review/", file=sys.stderr)
        sys.exit(1)

    store = {"schema_version": 1, "stages": collect(args.source)}

    bad = check_ascii(store["stages"])
    if bad:
        print("NON-ASCII FOUND (failing):")
        for k, items in bad.items():
            print("  ", k, items)
        sys.exit(2)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=True)
    print("WROTE", args.out)
    counts = {stage: len(cfg["prompts"]) for stage, cfg in store["stages"].items()}
    print("prompts per stage:", counts)

    # Round-trip check
    with open(args.out, encoding="utf-8") as f:
        rt = json.load(f)
    assert rt == store, "round-trip mismatch"
    print("round-trip OK")


if __name__ == "__main__":
    main()
