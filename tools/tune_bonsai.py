"""Tighten per-stage generation budgets for Bonsai-1.7B (vetting-gate result).

The review prompts encouraged very long output (4000-6000 max_tokens) which
the 1-bit model turns into rambling generations at a slow decode tail. The
prompt editor makes these the boss-tunable controls; this seeds them to values
that keep Bonsai fast while still producing complete structured findings.

ASCII only. Usage: python tools/tune_bonsai.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPTS = os.path.join(ROOT, "configs", "prompts.json")

# stage -> (max_tokens, temperature). Analysis/final stay concise; report can
# be a bit longer since it is the deliverable.
TUNE = {
    "s1_extract": (2048, 0.2),
    "s2_cross_section": (1024, 0.2),
    "s3_citations": (1024, 0.25),
    "s4_sme": (1024, 0.25),
    "s5_copyedit": (1024, 0.2),
    "s6_dedup": (1024, 0.0),
    "s7_report": (1500, 0.3),
}


def main():
    with open(PROMPTS, encoding="utf-8") as f:
        data = json.load(f)
    changed = []
    for stage, (mt, temp) in TUNE.items():
        cfg = data.get("stages", {}).get(stage)
        if not isinstance(cfg, dict):
            continue
        if cfg.get("max_tokens") != mt:
            cfg["max_tokens"] = mt
            changed.append(stage + ":mt")
        if cfg.get("temperature") != temp:
            cfg["temperature"] = temp
            changed.append(stage + ":temp")
    with open(PROMPTS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
    print("changed:", changed if changed else "(none)")
    raw = json.dumps(data, ensure_ascii=False)
    bad = sorted({c for c in raw if ord(c) > 127})
    print("ascii:", "CLEAN" if not bad else repr(bad))


if __name__ == "__main__":
    main()