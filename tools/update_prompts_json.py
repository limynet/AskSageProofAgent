"""Add references + model fields to configs/prompts.json (idempotent).

Every stage gains a `references` list (from stage_meta.DEFAULT_REFERENCES)
and keeps model/temperature/max_tokens editable values. Existing prompt text,
version, and updated_at are preserved; only the new fields are written when
absent.

ASCII/English only. Usage: python tools/update_prompts_json.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import stage_meta  # noqa: E402

PROMPTS_PATH = os.path.join(ROOT, "configs", "prompts.json")


def main():
    with open(PROMPTS_PATH, encoding="utf-8") as f:
        store = json.load(f)
    stages = store.get("stages") or {}
    changed = []
    for key, cfg in stages.items():
        if not isinstance(cfg, dict):
            continue
        if "references" not in cfg:
            cfg["references"] = list(stage_meta.DEFAULT_REFERENCES.get(key, []))
            changed.append(key)
        if "model" not in cfg:
            cfg["model"] = stage_meta.DEFAULT_MODEL.get(key, "local")
            changed.append(key)
    store["stages"] = stages
    with open(PROMPTS_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=True)
    print("updated stages:", changed if changed else "(none, already present)")
    # ASCII gate
    raw = json.dumps(store, ensure_ascii=False)
    bad = sorted({c for c in raw if ord(c) > 127})
    print("non-ascii:", bad if bad else "CLEAN")


if __name__ == "__main__":
    main()