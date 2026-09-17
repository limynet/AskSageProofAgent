"""Per-stage prompt configuration version history.

Each time the dashboard saves a node's prompt config, the config that is
about to be replaced is archived here first. Storage is one JSON file per
stage under configs/history/, newest entry first, capped at MAX_ENTRIES so
the folder stays small.

    append_history(stage, cfg)        # archive the replaced config
    load_history(stage) -> list      # entries: {version, saved_at, config}
    restore(stage, version)          # write an archived config back as a
                                     # NEW version (restores are undoable)

Restores bump the version like any save, so rolling back never loses the
state you rolled back from. ASCII/English only.
"""

import json
import os
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(BASE_DIR, "..", "configs", "history")
PROMPTS_PATH = os.path.join(BASE_DIR, "..", "configs", "prompts.json")
MAX_ENTRIES = 20


def _history_path(stage):
    """Return the history file path for one stage key."""
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in str(stage))
    return os.path.join(HISTORY_DIR, "%s.json" % safe)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_history(stage):
    """Return the archived entries for a stage, newest first (or [])."""
    path = _history_path(stage)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return [e for e in (entries or []) if isinstance(e, dict)]


def append_history(stage, cfg):
    """Archive the stage config that is about to be replaced.

    Deep-copies via a JSON round trip so later mutation of the caller's dict
    cannot rewrite the archived snapshot. No-op for empty configs and for a
    version already at the top of the stack (idempotent re-save).
    """
    if not isinstance(cfg, dict) or not cfg:
        return False
    entries = load_history(stage)
    if entries and entries[0].get("version") == cfg.get("version"):
        return False
    entry = {
        "version": cfg.get("version"),
        "saved_at": cfg.get("updated_at"),
        "archived_at": _now_iso(),
        "config": json.loads(json.dumps(cfg, ensure_ascii=True)),
    }
    entries.insert(0, entry)
    entries = entries[:MAX_ENTRIES]
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = _history_path(stage)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 1, "stage": stage, "entries": entries},
                  f, ensure_ascii=True, indent=2)
    os.replace(tmp_path, path)
    return True


def get_entry(stage, version):
    """Return one archived entry by version number, or None."""
    try:
        wanted = int(version)
    except (TypeError, ValueError):
        return None
    for entry in load_history(stage):
        try:
            if int(entry.get("version")) == wanted:
                return entry
        except (TypeError, ValueError):
            continue
    return None


def restore(stage, version):
    """Write an archived config back into prompts.json as a NEW version.

    Returns (ok, message). The restored config keeps its old prompts,
    model, temperature, max_tokens, outlet, and references, but carries a
    fresh version number and timestamp, so the restore itself appears in
    the history on the next save and can be undone.
    """
    entry = get_entry(stage, version)
    if entry is None:
        return False, "No archived version %s found for this node." % version
    try:
        with open(PROMPTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        return False, "Could not read configs/prompts.json: %s" % exc

    stages = data.get("stages") or {}
    current = stages.get(stage)
    if not isinstance(current, dict):
        return False, "No prompt configuration for this node."
    append_history(stage, current)

    restored = json.loads(json.dumps(entry.get("config") or {}, ensure_ascii=True))
    if not restored:
        return False, "The archived version was empty."
    restored["version"] = int(current.get("version") or 0) + 1
    restored["updated_at"] = _now_iso()
    stages[stage] = restored

    tmp_path = PROMPTS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
    os.replace(tmp_path, PROMPTS_PATH)
    return True, (
        "Restored version %s as version %d (archived %s)."
        % (entry.get("version"), restored["version"], entry.get("archived_at", ""))
    )