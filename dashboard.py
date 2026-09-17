"""
AskSage Proof Agent - Dash application entry point.

Single page, three zones:
  Zone 1  brand bar with the engine status pill
  Zone 2  left column: Manuscript panel and Review panel
  Zone 3  right column: Engine panel and Playground panel
  Zone 4  footer

The Flask instance lives on `app.server`, so gunicorn can serve
`dashboard:app.server` directly. Every callback is defensive: it renders an
inline error state instead of raising, so a missing backend module or an
unreachable model endpoint never takes the page down.

Backend modules are imported lazily inside the callbacks. They are being
written in parallel, and the UI must start without them.
"""

import base64
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone

from dash import Dash, Input, Output, State, dcc, html, no_update

try:  # Dash 3+/4 exposes the wildcard marker here; older builds do not.
    from dash import ALL as dash_ALL
except ImportError:  # pragma: no cover - the wildcard inputs are optional
    dash_ALL = None

# --------------------------------------------------------------------------
# Configuration - environment variables with safe defaults, no secrets inline
# --------------------------------------------------------------------------

LOCAL_API_BASE = os.getenv("LOCAL_API_BASE", "http://maple-llm:8080/v1")
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "bonsai-1.7b")
CUSTOM_API_BASE = os.getenv("CUSTOM_API_BASE", "")
CUSTOM_MODEL = os.getenv("CUSTOM_MODEL", "")
CUSTOM_API_KEY = os.getenv("CUSTOM_API_KEY", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, "src")
DATA_DIR = os.path.join(BASE_DIR, "data")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# --------------------------------------------------------------------------
# UI copy constants
# --------------------------------------------------------------------------

EMPTY_VALUE = "-"
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
SEVERITY_LABEL = {"error": "Error", "warning": "Warning", "info": "Info"}

FOOTER_TEXT = "Local prototype | Bonsai-1.7B (local) with custom API fallback"

# The single swap point for the review engine. Point this at the module that
# exposes run_review and the rest of the UI follows unchanged.
# Default is the proven 7-stage engine (pub_pipeline). Set
# REVIEW_ENGINE=review_agents in the environment to keep the legacy chunked
# engine. Both expose the same run_review(text, ...) contract.
REVIEW_ENGINE = os.getenv("REVIEW_ENGINE", "pub_pipeline")

# The single swap point for the LLM client. Point this at the module that
# exposes LLMClient and the rest of the UI follows unchanged.
LLM_MODULE = "llm_client"

# The single swap point for the summary letter builder.
SUMMARY_MODULE = "summary_letter"

# --------------------------------------------------------------------------
# Pipeline module state
#
# The seven stage cards are driven by one PipelineState object. It is kept in
# a module-level global rather than in a dcc.Store because the background
# runner mutates the same object from its worker thread; the dcc.Store only
# carries the serialized snapshot the browser renders.
#
# The runner module is imported lazily inside the callbacks, so this file
# still imports and the layout still builds when src/ is unavailable.
# --------------------------------------------------------------------------

#: The live ReviewRun instance, or None when no agent pass is in flight.
_ACTIVE_RUN = None

#: In-memory run ledger. Newest entry first, capped at LEDGER_LIMIT rows.
_RUN_LEDGER = []

#: Maximum number of ledger rows kept in memory.
LEDGER_LIMIT = 30

#: The document dict the pipeline was last built for, used to ignore repeat
#: store-document updates that carry the same manuscript.
_LAST_DOC = None

#: Per-persona approval selection behind the three toggle chips.
_AGENT_SELECTION = {"s3_citations": True, "s4_sme": True, "s5_copyedit": True}

#: Human labels for the seven pipeline stages.
PIPELINE_STAGE_LABELS = {
    "s1_extract": "Extract & Parse",
    "s2_cross_section": "Cross-Section Analysis",
    "s3_citations": "Citations & APA Review",
    "s4_sme": "SME + Statistics Review",
    "s5_copyedit": "CopyEdit + Bias + Originality",
    "s6_dedup": "Dedup & Consolidate",
    "s7_report": "Final Report",
}

#: The stage order the strip renders. Mirrors pipeline.VALID_STAGES; it is
#: duplicated here so the layout can be built without importing src/.
PIPELINE_STAGE_ORDER = [
    "s1_extract",
    "s2_cross_section",
    "s3_citations",
    "s4_sme",
    "s5_copyedit",
    "s6_dedup",
    "s7_report",
]

#: Persona name to pipeline stage name. Mirrors runner.PERSONA_STAGES.
PERSONA_STAGE = {
    "citation": "s3_citations",
    "apa": "s4_sme",
    "sme": "s5_copyedit",
}

#: Stage name to persona name (the inverse of PERSONA_STAGE).
STAGE_PERSONA = {
    "s3_citations": "citation",
    "s4_sme": "apa",
    "s5_copyedit": "sme",
}

#: Status word shown on a stage badge.
STATUS_LABEL = {
    "pending": "Pending",
    "running": "Running",
    "done": "Done",
    "skipped": "Skipped",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "awaiting_approval": "Awaiting approval",
}

#: Statuses that mean a stage has stopped and will not continue on its own.
TERMINAL_STATUS = ("done", "skipped", "failed", "cancelled")

#: Fallback stage rows used to render an empty strip before any upload.
EMPTY_STAGE_ROWS = [
    {
        "name": name,
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "count": 0,
        "detail": "",
    }
    for name in PIPELINE_STAGE_ORDER
]


def _pipeline_state():
    """
    Build a fresh PipelineState, or None when the module is unavailable.

    The import is deliberately lazy: the dashboard must still start, and the
    strip must still render, when src/pipeline.py cannot be imported.
    """
    try:
        from pipeline import PipelineState

        return PipelineState()
    except Exception as exc:  # noqa: BLE001 - the strip degrades to static rows
        _log("pipeline module unavailable: %s" % exc)
        return None


def _pipeline_from_states(states):
    """Rebuild a PipelineState from a serialized snapshot, or None."""
    try:
        from pipeline import PipelineState

        return PipelineState.from_dict(states or {})
    except Exception as exc:  # noqa: BLE001 - the caller falls back to a fresh state
        _log("pipeline restore failed: %s" % exc)
        return None


def _stage_rows(states):
    """
    Return the seven stage dicts to render, from a snapshot or from scratch.

    A malformed or missing snapshot never raises: unknown or absent stages
    are filled in as "pending" rows so the strip always has seven cards.
    """
    rows = {}
    if isinstance(states, dict):
        for item in states.get("stages", []) or []:
            if isinstance(item, dict) and item.get("name") in PIPELINE_STAGE_ORDER:
                rows[item["name"]] = {
                    "name": item["name"],
                    "status": _text(item.get("status")) or "pending",
                    "started_at": item.get("started_at"),
                    "finished_at": item.get("finished_at"),
                    "count": item.get("count", 0) or 0,
                    "detail": _text(item.get("detail")),
                }
    return [rows.get(name, dict(EMPTY_STAGE_ROWS[index]))
            for index, name in enumerate(PIPELINE_STAGE_ORDER)]


def _rules_done(states):
    """Return True when the deterministic rules stage has completed."""
    for row in _stage_rows(states):
        if row["name"] == "s2_cross_section":
            return row["status"] == "done"
    return False


def _approvable_agents(states):
    """Return the agent stages a human may approve right now.

    An agent stage is approvable while the cross-section/rules pass is done
    and the stage has not started yet, which covers both "pending" and the
    explicit "awaiting_approval" status the upload gate sets.
    """
    if not _rules_done(states):
        return []
    rows = {row["name"]: row for row in _stage_rows(states)}
    return [
        name
        for name in ("s3_citations", "s4_sme", "s5_copyedit")
        if rows.get(name, {}).get("status") in ("pending", "awaiting_approval")
    ]


def _ledger_add(stage, status, count=0, detail="", started_at=None, finished_at=None):
    """Append one run-ledger row, newest first, dropping the oldest rows."""
    try:
        _RUN_LEDGER.insert(
            0,
            {
                "stage": _text(stage) or "run",
                "label": PIPELINE_STAGE_LABELS.get(_text(stage), _text(stage) or "Run"),
                "status": _text(status) or "pending",
                "count": int(count or 0),
                "detail": _text(detail, 160),
                "started_at": _text(started_at),
                "finished_at": _text(finished_at),
            },
        )
        del _RUN_LEDGER[LEDGER_LIMIT:]
    except Exception as exc:  # noqa: BLE001 - the ledger must never break a run
        _log("ledger add failed: %s" % exc)


def _short_time(value):
    """Reduce an ISO-8601 timestamp to a short HH:MM:SS clock string."""
    stamp = _text(value)
    if not stamp:
        return ""
    try:
        return stamp[11:19] if len(stamp) >= 19 else stamp
    except Exception:  # noqa: BLE001 - a malformed stamp is simply not shown
        return ""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _log(message):
    """Write a diagnostic line to stderr without ever raising."""
    try:
        sys.stderr.write("[dashboard] %s\n" % message)
        sys.stderr.flush()
    except Exception:
        pass


def _text(value, limit=None):
    """Coerce any value to a plain string, optionally truncated."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if limit is not None and len(value) > limit:
        value = value[:limit].rstrip() + " ..."
    return value


def _safe_name(filename):
    """Reduce an uploaded filename to a safe basename for data/."""
    name = os.path.basename(_text(filename) or "manuscript")
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip()
    name = name.lstrip(".") or "manuscript"
    return name[:120]


def _provider_config(provider):
    """
    Return display and connection details for one provider key.

    The keys match the provider registry used by the LLM client, so the
    dashboard and the client always agree on what "local" and "custom" mean.
    """
    if provider == "custom":
        return {
            "key": "custom",
            "label": "Custom API",
            "base": CUSTOM_API_BASE,
            "model": CUSTOM_MODEL,
            "endpoint": CUSTOM_API_BASE or "Not configured",
            "fallback": "Local (Bonsai)",
            "configured": bool(CUSTOM_API_BASE and CUSTOM_MODEL and CUSTOM_API_KEY),
            "note": "API key loaded from environment"
            if CUSTOM_API_KEY
            else "No API key set in the environment",
        }
    return {
        "key": "local",
        "label": "Local (Bonsai)",
        "base": LOCAL_API_BASE,
        "model": LOCAL_MODEL,
        "endpoint": LOCAL_API_BASE,
        "fallback": "Custom API" if CUSTOM_API_BASE else "None configured",
        "configured": True,
        "note": "Local endpoint, no API key required",
    }


def _provider_key(provider):
    """Normalize the provider store value to a key ("local"/"custom").

    The store normally holds {"provider": key}, but defensive callers (and
    older probe harnesses) may pass a bare string; both are accepted so a
    malformed value can never crash the engine panel callbacks.
    """
    if isinstance(provider, dict):
        return _text(provider.get("provider")) or "local"
    return _text(provider) or "local"


def _status_pill(state, label):
    """Build the brand-bar status pill. State is one of untested/connected/offline."""
    state = state if state in ("untested", "connected", "offline") else "untested"
    return html.Div(
        id="status-pill",
        className="status-pill is-" + state,
        children=[
            html.Span(className="status-dot", **{"aria-hidden": "true"}),
            html.Span(_text(label) or "Untested", id="status-text", className="status-text"),
        ],
        role="status",
    )


def _alert(heading, body, next_step):
    """Inline alert bar. Replaces modal dialogs and alert() entirely."""
    return html.Div(
        className="alert",
        role="alert",
        children=[
            html.Div(_text(heading), className="alert-heading"),
            html.Div(_text(body), className="alert-body"),
            html.Div(_text(next_step), className="alert-next"),
        ],
    )


def _skeleton_rows(count=3, block=False):
    """Loading placeholder shaped like the region it replaces."""
    rows = []
    for index in range(count):
        if block and index == 0:
            rows.append(html.Div(className="skeleton is-block"))
        else:
            width = ["is-full", "is-medium", "is-short"][index % 3]
            rows.append(html.Div(className="skeleton " + width))
    return html.Div(className="skeleton-group", children=rows)


def _provenance_for(finding):
    """
    Return a short provenance tag for one finding.

    Rule findings carry a standard reference in "source" (for example
    "APA 7 section 8.10") and the deterministic agent name, so they are
    tagged "Rule". Findings produced by the background LLM runner carry a
    "provenance" key written by the dashboard, so they are tagged with the
    agent and the model that produced them. Anything unrecognized is left
    untagged rather than guessed at.
    """
    if not isinstance(finding, dict):
        return ""
    provenance = _text(finding.get("provenance")).strip()
    if provenance:
        return provenance
    if _text(finding.get("source")).strip():
        return "Rule"
    return ""


def _finding_card(finding):
    """Render one finding dict as a card."""
    severity = _text(finding.get("severity", "info")).lower()
    if severity not in SEVERITY_ORDER:
        severity = "info"
    location = _text(finding.get("location")) or "Document"
    excerpt = _text(finding.get("excerpt"))
    source = _text(finding.get("source"))
    provenance = _provenance_for(finding)

    head = [
        html.Span(
            SEVERITY_LABEL[severity],
            className="severity-tag is-" + severity,
        ),
        html.Span(_text(finding.get("agent")) or "Review", className="finding-agent"),
    ]
    if provenance:
        head.append(html.Span(provenance, className="provenance-tag"))
    head.append(html.Span(location, className="finding-location"))

    children = [html.Div(className="finding-head", children=head)]

    if excerpt:
        children.append(html.Blockquote(excerpt, className="finding-excerpt"))

    children.append(
        html.Div(
            className="finding-line",
            children=[
                html.Span("Issue: ", className="finding-line-label"),
                html.Span(_text(finding.get("issue")) or "No issue text was returned."),
            ],
        )
    )
    children.append(
        html.Div(
            className="finding-line is-fix",
            children=[
                html.Span("Suggested fix: ", className="finding-line-label"),
                html.Span(_text(finding.get("fix")) or "No suggested fix was returned."),
            ],
        )
    )

    if source:
        children.append(html.Div("Source: " + source, className="finding-source"))

    return html.Article(className="finding-card", children=children)


def _findings_view(findings, selected_filter):
    """Render the findings board body for the selected filter chip."""
    if not findings:
        return html.Div(
            "No review has been run yet. Upload a manuscript and select Run review.",
            className="board-empty",
        )

    selected = (selected_filter or "all").lower()
    if selected == "errors":
        visible = [f for f in findings if _text(f.get("severity")).lower() == "error"]
    elif selected == "warnings":
        visible = [f for f in findings if _text(f.get("severity")).lower() == "warning"]
    else:
        visible = list(findings)

    if not visible:
        return html.Div(
            "No findings match this filter. Select All to see the full review.",
            className="board-empty",
        )

    ordered = sorted(visible, key=lambda f: SEVERITY_ORDER.get(_text(f.get("severity")).lower(), 3))
    return html.Div(className="findings-list", children=[_finding_card(f) for f in ordered])


def _normalize_finding(item):
    """Map one raw finding dict onto the keys the cards render."""
    severity = _text(item.get("severity", "info")).lower()
    if severity not in SEVERITY_ORDER:
        severity = "info"
    return {
        "severity": severity,
        "agent": _text(item.get("agent") or item.get("agent_name") or "Review"),
        "location": _text(item.get("location") or item.get("page") or ""),
        "excerpt": _text(item.get("original_text") or item.get("excerpt") or item.get("original") or ""),
        "issue": _text(item.get("issue") or item.get("problem") or ""),
        "fix": _text(item.get("suggested_fix") or item.get("fix") or item.get("suggestion") or ""),
        "source": _text(item.get("source") or item.get("standard") or ""),
    }


def _parse_findings(payload):
    """Normalize whatever the review engine returns into a list of finding dicts."""
    if payload is None:
        return []
    if isinstance(payload, dict):
        for key in ("findings", "results", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        return []

    findings = []
    for item in payload:
        if isinstance(item, dict):
            findings.append(_normalize_finding(item))
    return findings


def _placeholder_finding(message):
    """Single info-level finding used while the review engine is not wired."""
    return {
        "severity": "info",
        "agent": "Review engine",
        "location": "Whole document",
        "excerpt": "",
        "issue": message,
        "fix": "The interface is complete and will render findings as soon as the review engine returns them.",
        "source": "AskSage Proof Agent",
    }


def _fallback_findings():
    """
    Findings shown when the review engine is unavailable.

    Swapping in the real engine means changing REVIEW_ENGINE above to the
    module that exposes `run_review(text, options)`.
    """
    return [
        _placeholder_finding(
            "The review engine is not wired yet, so no citation or style checks were performed."
        )
    ]


def _agent_labels(selected):
    """Map the checklist values onto the agent names the engine understands."""
    mapping = {"citation": "citation", "apa7": "apa", "army": "sme"}
    chosen = [mapping[value] for value in (selected or []) if value in mapping]
    return tuple(chosen) if chosen else ("citation", "apa", "sme")


def _call_review_engine(text, options):
    """
    Invoke the review engine if it is importable.

    Returns (findings, error_message). A one-line change to REVIEW_ENGINE
    points this at a different implementation.
    """
    try:
        module = __import__(REVIEW_ENGINE, fromlist=["run_review"])
        runner = getattr(module, "run_review", None)
        if runner is None:
            return None, "Review engine module has no run_review function."
        return _parse_findings(runner(text, agents=_agent_labels(options))), None
    except ImportError as exc:
        return None, "Review engine module is not available: %s" % exc
    except Exception as exc:  # noqa: BLE001 - surface any engine failure inline
        _log("review engine failed: %s" % traceback.format_exc().splitlines()[-1])
        return None, "Review engine failed: %s" % exc


def _build_llm_client(provider_key):
    """
    Build an LLM client for the selected provider.

    Returns (client, error_message). The client is duck-typed: only
    chat_completion is required, so any compatible backend can be swapped in
    through LLM_MODULE.
    """
    try:
        module = __import__(LLM_MODULE, fromlist=["LLMClient"])
    except ImportError as exc:
        return None, "LLM client module is not available: %s" % exc

    client_class = getattr(module, "LLMClient", None)
    if client_class is None:
        return None, "LLM client module exposes no LLMClient class."

    last_error = None
    for kwargs in ({"model_type": provider_key}, {}):
        try:
            return client_class(**kwargs), None
        except Exception as exc:  # noqa: BLE001 - try the next signature
            last_error = exc
    return None, "Could not construct an LLM client: %s" % last_error


def _call_llm(provider, prompt, system_prompt=None):
    """
    Invoke the LLM client if it is importable.

    Returns (response_text, error_message). This is the only place the UI
    talks to a model, so a different backend only changes this function.
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    client, error = _build_llm_client(provider)
    if client is None:
        return None, error

    try:
        if hasattr(client, "chat_completion"):
            result = client.chat_completion(messages=messages, temperature=0.2, max_tokens=1200)
        elif hasattr(client, "complete"):
            result = client.complete(prompt)
        elif hasattr(client, "chat"):
            result = client.chat(messages)
        else:
            return None, "LLM client exposes no supported completion method."
        return _text(result), None
    except Exception as exc:  # noqa: BLE001 - surface any transport failure inline
        _log("llm call failed: %s" % traceback.format_exc().splitlines()[-1])
        return None, "The engine did not answer: %s" % exc


def _triggered_chip():
    """Resolve which filter chip fired, tolerating a missing callback context."""
    triggered = None
    try:
        from dash import ctx

        triggered = ctx.triggered_id
    except Exception:  # noqa: BLE001 - fall back to the default chip
        triggered = None
    mapping = {
        "filter-all": ("all", "filter-all"),
        "filter-errors": ("errors", "filter-errors"),
        "filter-warnings": ("warnings", "filter-warnings"),
    }
    return mapping.get(triggered, ("all", "filter-all"))


def _summary_markdown(document_name, metrics, findings, provider_label, provider_key="local"):
    """
    Build the Markdown summary letter returned by the export button.

    The shared summary_letter module is used when it is importable, so the
    exported letter and the rest of the app stay in one format. The local
    builder is the fallback and always produces ASCII-only Markdown.
    """
    try:
        module = __import__(SUMMARY_MODULE, fromlist=["build_summary_letter"])
        builder = getattr(module, "build_summary_letter", None)
        if callable(builder):
            review_result = {
                "findings": [
                    {
                        "agent": _text(item.get("agent")),
                        "severity": _text(item.get("severity", "info")).lower(),
                        "location": _text(item.get("location")) or "document",
                        "original_text": _text(item.get("excerpt")),
                        "issue": _text(item.get("issue")),
                        "suggested_fix": _text(item.get("fix")),
                        "source": _text(item.get("source")),
                    }
                    for item in (findings or [])
                ],
                "summary": {},
                "manuscript": document_name or "No document loaded",
                "metrics": dict(metrics or {}),
                "provider": provider_key,
            }
            counts = {"error": 0, "warning": 0, "info": 0, "total": 0}
            for item in review_result["findings"]:
                severity = item["severity"] if item["severity"] in counts else "info"
                counts[severity] += 1
                counts["total"] += 1
            review_result["summary"] = counts
            letter = builder(document_name or "No document loaded", review_result, provider_label)
            if _text(letter).strip():
                return letter
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - fall back to the local builder
        _log("summary letter module failed: %s" % exc)

    lines = [
        "# Manuscript review summary",
        "",
        "Generated: %s" % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "Engine: %s" % provider_label,
        "",
        "## Document",
        "",
        "- File: %s" % (document_name or "No document loaded"),
        "- Format: %s" % metrics.get("format", EMPTY_VALUE),
        "- Pages: %s" % metrics.get("pages", EMPTY_VALUE),
        "- Words: %s" % metrics.get("words", EMPTY_VALUE),
        "- Characters: %s" % metrics.get("characters", EMPTY_VALUE),
        "",
        "## Findings",
        "",
    ]

    if not findings:
        lines.append("No review has been run yet.")
    else:
        counts = {"error": 0, "warning": 0, "info": 0}
        for finding in findings:
            severity = _text(finding.get("severity")).lower()
            counts[severity if severity in counts else "info"] += 1
        lines.append(
            "Totals: %d errors, %d warnings, %d informational notes."
            % (counts["error"], counts["warning"], counts["info"])
        )
        lines.append("")
        for index, finding in enumerate(findings, start=1):
            severity = _text(finding.get("severity", "info")).lower()
            lines.append("### %d. %s - %s" % (index, SEVERITY_LABEL.get(severity, "Info"), _text(finding.get("agent")) or "Review"))
            lines.append("")
            lines.append("- Location: %s" % (_text(finding.get("location")) or "Document"))
            if _text(finding.get("excerpt")):
                lines.append("- Excerpt: %s" % _text(finding.get("excerpt")))
            lines.append("- Issue: %s" % (_text(finding.get("issue")) or "Not provided"))
            lines.append("- Suggested fix: %s" % (_text(finding.get("fix")) or "Not provided"))
            if _text(finding.get("source")):
                lines.append("- Source: %s" % _text(finding.get("source")))
            lines.append("")

    lines.extend(
        [
            "## Next steps",
            "",
            "1. Resolve the errors listed above before resubmission.",
            "2. Confirm every citation against the APA 7 reference list.",
            "3. Re-run the review after edits and export a fresh summary.",
            "",
            "Prepared by AskSage Proof Agent.",
        ]
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Pipeline stage -> configs/prompts.json key.
#
# The stage keys and the prompts.json stage keys are the same identifiers
# (s1_extract..s7_report), so `stage` is used directly and no lookup map is
# needed.
# --------------------------------------------------------------------------



# --------------------------------------------------------------------------
# Pipeline strip renderers
#
# Every renderer here is a pure function of the serialized pipeline snapshot
# and never raises: a malformed snapshot produces a fully pending strip
# instead of taking the page down.
# --------------------------------------------------------------------------


def _stage_count_text(row):
    """Return the small count string for a stage card, or an empty string."""
    status = _text(row.get("status"))
    count = row.get("count", 0) or 0
    name = _text(row.get("name"))

    if name == "s2_cross_section":
        if status in ("done", "running"):
            return "%s rule hit%s" % (count, "" if count == 1 else "s")
        return ""
    if name in STAGE_PERSONA:
        if status in ("done", "running", "cancelled", "failed"):
            return "%s finding%s" % (count, "" if count == 1 else "s")
        return ""
    if name == "s7_report" and status == "done":
        return "ready"
    return ""


def _render_stage_card(row, selected=False):
    """Render one stage card: label, status badge, count, and detail line."""
    name = _text(row.get("name"))
    status = _text(row.get("status")) or "pending"
    if status not in STATUS_LABEL:
        status = "pending"

    count_text = _stage_count_text(row)
    detail = _text(row.get("detail"))

    meta = [html.Span(count_text, className="pipe-count")] if count_text else []
    if detail:
        meta.append(html.Span(detail, className="pipe-detail"))

    # A finished, failed, or cancelled agent stage offers a single-persona
    # re-run. The persona rides on the id and on a data attribute so the
    # callback can tell which button fired.
    rerun = None
    persona = STAGE_PERSONA.get(name)
    if persona and status in TERMINAL_STATUS:
        rerun = html.Button(
            "Re-run",
            id={"type": "agent-rerun", "persona": persona},
            className="pipe-rerun",
            n_clicks=0,
            type="button",
            **{"data-persona": persona},
        )

    return html.Div(
        id={"type": "stage-card", "stage": name},
        className="pipe-card is-" + status + (" is-selected" if selected else ""),
        **{"data-stage": name},
        children=[
            html.Button(
                id={"type": "stage-focus", "stage": name},
                className="pipe-card-btn",
                n_clicks=0,
                type="button",
                **{"data-stage": name, "aria-pressed": "true" if selected else "false"},
                children=[
                    html.Span(PIPELINE_STAGE_LABELS.get(name, name), className="pipe-label"),
                    html.Span(
                        className="pipe-badge is-" + status,
                        children=[
                            html.Span(className="pipe-dot", **{"aria-hidden": "true"}),
                            html.Span(STATUS_LABEL[status], className="pipe-status"),
                        ],
                    ),
                    html.Span(meta, className="pipe-meta"),
                ],
            ),
            rerun,
        ],
    )


def _render_approval_bar(states):
    """Render the human approval gate for the three agent stages.

    The bar is empty unless the deterministic rules pass has finished and at
    least one agent stage is still pending, which is exactly the gate
    PipelineState.approvable_agents(rules_done=True) describes.
    """
    approvable = _approvable_agents(states)
    if not approvable:
        return html.Div(id="pipe-approval", className="pipe-approval is-hidden")

    rows = _stage_rows(states)
    rules_row = rows[PIPELINE_STAGE_ORDER.index("s2_cross_section")]
    hits = rules_row.get("count", 0) or 0

    toggles = []
    for persona in ("citation", "apa", "sme"):
        stage_name = PERSONA_STAGE[persona]
        if stage_name not in approvable:
            continue
        toggles.append(
            {
                "label": PIPELINE_STAGE_LABELS[stage_name],
                "value": persona,
            }
        )

    return html.Div(
        id="pipe-approval",
        className="pipe-approval",
        children=[
            html.Div(
                className="pipe-approval-head",
                children=[
                    html.Span("Approval gate", className="pipe-approval-title"),
                    html.Span(
                        "The deterministic rules pass finished with %s rule hit%s. "
                        "The three agent passes need your approval."
                        % (hits, "" if hits == 1 else "s"),
                        className="pipe-approval-note",
                    ),
                ],
            ),
            dcc.Checklist(
                id="agent-toggle",
                className="pipe-toggles",
                options=toggles,
                value=[item["value"] for item in toggles],
            ),
            html.Div(
                className="btn-row",
                children=[
                    html.Button(
                        "Run selected agents",
                        id="run-agents",
                        className="btn btn-primary",
                        n_clicks=0,
                        type="button",
                    )
                ],
            ),
            html.Div(
                "Approx %s chunks; several minutes on the local model."
                % _estimate_chunks(_LAST_DOC),
                id="pipe-estimate",
                className="pipe-estimate",
            ),
        ],
    )


def _estimate_chunks(document):
    """Estimate the chunk count for one agent pass over the manuscript.

    This mirrors the reviewer's chunking (paragraphs joined up to a fixed
    character budget) without importing src/, so the estimate is available
    even while the runner module is unavailable.
    """
    text = _text((document or {}).get("text"))
    if not text.strip():
        return 1
    paragraphs = re.split(r"\n\s*\n", text)
    chunks = 0
    current_len = 0
    for paragraph in paragraphs:
        paragraph_len = len(paragraph) + 2
        if current_len and current_len + paragraph_len > REVIEW_CHUNK_CHARS:
            chunks += 1
            current_len = 0
        current_len += paragraph_len
    if current_len:
        chunks += 1
    return max(1, chunks)


def _stage_detail_body(row, states):
    """Render the INNER content of the stage detail panel (no wrapper id).

    This is what Output("stage-detail", "children") receives on a stage
    click. It must NOT contain an element with id="stage-detail": nesting a
    wrapper inside its own output made every click embed another full copy
    of the panel (the "multiple box" bug).
    """
    name = _text(row.get("name"))
    status = _text(row.get("status")) or "pending"
    if status not in STATUS_LABEL:
        # An unselected stage has no status of its own; the panel is empty
        # until a card is clicked.
        return [
            html.Div(
                className="stage-detail-head",
                children=[
                    html.Span("Stage detail", className="stage-detail-title"),
                    html.Span(
                        "Select a stage card to inspect it.",
                        className="stage-detail-note",
                    ),
                ],
            ),
            html.Div(
                "No stage selected yet.",
                className="board-empty",
            ),
        ]

    label = PIPELINE_STAGE_LABELS.get(name, name or "Stage")
    detail = _text(row.get("detail"))

    rows = [
        html.Div(
            className="kv-row",
            children=[
                html.Span("Stage", className="kv-key"),
                html.Span(label, className="kv-value"),
            ],
        ),
        html.Div(
            className="kv-row",
            children=[
                html.Span("Status", className="kv-key"),
                html.Span(STATUS_LABEL.get(status, status), className="kv-value"),
            ],
        ),
        html.Div(
            className="kv-row",
            children=[
                html.Span("Count", className="kv-key"),
                html.Span(_text(row.get("count", 0) or 0), className="kv-value"),
            ],
        ),
        html.Div(
            className="kv-row",
            children=[
                html.Span("Started", className="kv-key"),
                html.Span(_short_time(row.get("started_at")) or EMPTY_VALUE, className="kv-value"),
            ],
        ),
        html.Div(
            className="kv-row",
            children=[
                html.Span("Finished", className="kv-key"),
                html.Span(_short_time(row.get("finished_at")) or EMPTY_VALUE, className="kv-value"),
            ],
        ),
    ]

    if detail:
        rows.append(
            html.Div(
                className="kv-row",
                children=[
                    html.Span("Detail", className="kv-key"),
                    html.Span(detail, className="kv-value"),
                ],
            )
        )

    body = [html.Div(className="kv-list", children=rows)]

    # Sub-step flow + prompt editor for stages that have a prompt config.
    body.extend(_render_prompt_editor(name))

    return [
        html.Div(
            className="stage-detail-head",
            children=[
                html.Span("%s stage" % label, className="stage-detail-title"),
                html.Span(
                    "Click a stage to expand its prompt configuration.",
                    className="stage-detail-note",
                ),
            ],
        ),
        html.Div(className="stage-detail-body", children=body),
        html.Div(id="inspector-status", className="canvas-inspector-status"),
    ]


def _render_stage_detail(row, states):
    """Render the stage detail panel with its id wrapper (layout use only).

    Callbacks must use _stage_detail_body for Output("stage-detail",
    "children"); wrapping the wrapper nests the panel inside itself.
    """
    return html.Div(
        id="stage-detail",
        className="stage-detail",
        children=_stage_detail_body(row, states),
    )


def _reference_keys():
    """Return the registered reference document keys, or [] if unavailable."""
    try:
        import references

        return [d.get("key") for d in (references.load_registry().get("documents") or [])]
    except Exception:  # noqa: BLE001 - no reference module, no keys
        return []


# Upload constraints for reference documents (the RAG attachments).
_REF_UPLOAD_EXTS = (".txt", ".md", ".pdf", ".docx")
_REF_UPLOAD_MAX_BYTES = 30 * 1024 * 1024


def _save_reference_document(doc_key, filename, contents):
    """Decode an uploaded reference file and store it under data/reference/.

    The stored base name follows the registry entry for doc_key, so
    references.load_registry() finds it on the next read. Returns
    (ok, message).
    """
    try:
        import references as refmod

        docs = (refmod.load_registry().get("documents") or [])
        doc = next((d for d in docs if d.get("key") == doc_key), None)
        if doc is None:
            return False, "Unknown reference document: %s" % doc_key

        registered = _text(doc.get("file_abs"))
        if registered:
            base = os.path.splitext(registered)[0]
        else:
            base = os.path.join(DATA_DIR, "reference", doc_key)

        name = _safe_name(filename)
        ext = os.path.splitext(name)[1].lower()
        if ext not in _REF_UPLOAD_EXTS:
            return False, (
                "Unsupported file type %s. Use one of: .txt, .md, .pdf, .docx"
                % (ext or "(none)")
            )
        if not contents:
            return False, "The uploaded file was empty."

        _, _, payload = contents.partition(",")
        raw = base64.b64decode(payload)
        if not raw:
            return False, "The uploaded file was empty."
        if len(raw) > _REF_UPLOAD_MAX_BYTES:
            return False, "The file is larger than 30 MB. Export a text version first."

        os.makedirs(os.path.dirname(base), exist_ok=True)
        target = base + ext
        with open(target, "wb") as handle:
            handle.write(raw)

        # Keep exactly one variant: drop sibling extensions of the same doc.
        for alt in _REF_UPLOAD_EXTS:
            if alt == ext:
                continue
            sibling = base + alt
            if os.path.isfile(sibling):
                try:
                    os.remove(sibling)
                except OSError:
                    pass
        return True, "Saved %s to data/reference/." % os.path.basename(target)
    except Exception as exc:  # noqa: BLE001 - upload must never crash the app
        return False, "Could not save the reference file: %s" % exc


def _render_prompt_editor(stage_id):
    """Render the prompt editor block for a stage, or nothing.

    Reads configs/prompts.json through the prompt store. The textareas use
    the pattern-matching id {"type": "inspector-prompt", "key": KEY} that the
    save callback reads, so edits persist to disk with a version bump. The
    sub-step flow labels come from stage_meta.
    """
    key = stage_id
    if key not in PIPELINE_STAGE_ORDER:
        return []

    try:
        from stage_meta import STAGE_TITLES, sub_steps
    except Exception:  # noqa: BLE001 - the editor degrades to a simple list
        STAGE_TITLES, sub_steps = {}, None

    store = None
    try:
        from prompts import load_store

        store = load_store()[0]
    except Exception as exc:  # noqa: BLE001 - treat an unreadable store as absent
        _log("prompt store unavailable: %s" % exc)

    cfg = None
    if store is not None:
        try:
            from prompts import find_stage_config

            cfg = find_stage_config(store, key)
        except Exception:  # noqa: BLE001 - no config means no editor
            cfg = None
    if cfg is None:
        return []

    prompts = cfg.get("prompts") if isinstance(cfg.get("prompts"), dict) else {}
    if not prompts:
        return []

    # The save callback zips the stage's sorted prompt keys with the values
    # it receives, so textareas must be emitted in exactly that order.
    ordered_keys = sorted(prompts.keys())
    key_to_label = {}
    color_by = {}
    if sub_steps is not None:
        for step in sub_steps(stage_id):
            for pk in step.get("prompt_keys", []):
                key_to_label[pk] = step.get("label", pk)
    else:
        for pk in ordered_keys:
            key_to_label[pk] = pk

    version = cfg.get("version", "-")
    updated_at = _text(cfg.get("updated_at")) or "-"

    fields = [
        html.H4("Prompt configuration", className="canvas-inspector-head"),
        html.Div(
            "Stage %s | model %s | prompt v%s | updated %s"
            % (
                key,
                _text(cfg.get("model")) or "-",
                version,
                updated_at,
            ),
            className="canvas-inspector-meta",
        ),
    ]

    # Model / temperature / max tokens controls (requirement 2), plus the
    # per-node Outlet selector: which API entry point this stage calls.
    outlet_options = [{"label": "Engine default (Engine panel)", "value": ""}]
    try:
        import outlets as outlets_mod

        for o in (outlets_mod.load_outlets().get("outlets") or []):
            outlet_options.append(
                {"label": o.get("title") or o.get("key"), "value": o.get("key")}
            )
    except Exception:  # noqa: BLE001 - registry absent: default option only
        pass

    fields.append(
        html.Div(
            className="canvas-field-row",
            children=[
                html.Div(
                    className="canvas-field",
                    children=[
                        html.Label("Outlet", className="canvas-field-label", htmlFor="inspector-outlet"),
                        dcc.Dropdown(
                            id="inspector-outlet",
                            options=outlet_options,
                            value=_text(cfg.get("outlet")) or "",
                            clearable=False,
                            className="canvas-inp",
                        ),
                    ],
                ),
            ],
        ),
    )
    fields.append(
        html.Div(
            "Outlet: the API entry point this node calls. Engine default "
            "follows the Engine panel selection; other entries come from "
            "configs/outlets.json.",
            className="canvas-ref-muted",
        )
    )

    # Model / temperature / max tokens controls (requirement 2).
    fields.append(
        html.Div(
            className="canvas-field-row",
            children=[
                html.Div(
                    className="canvas-field",
                    children=[
                        html.Label("Model", className="canvas-field-label", htmlFor="inspector-model"),
                        dcc.Input(id="inspector-model", value=_text(cfg.get("model")),
                                  className="canvas-inp", type="text"),
                    ],
                ),
                html.Div(
                    className="canvas-field",
                    children=[
                        html.Label("Temperature", className="canvas-field-label", htmlFor="inspector-temp"),
                        dcc.Input(id="inspector-temp", type="number", value=cfg.get("temperature"),
                                  step=0.1, min=0, max=2, className="canvas-inp"),
                    ],
                ),
                html.Div(
                    className="canvas-field",
                    children=[
                        html.Label("Max tokens", className="canvas-field-label", htmlFor="inspector-max-tokens"),
                        dcc.Input(id="inspector-max-tokens", type="number", value=cfg.get("max_tokens"),
                                  step=1, min=1, max=32000, className="canvas-inp"),
                    ],
                ),
            ],
        ),
    )

    # Pointer for the per-node model choice (Part 2).
    fields.append(
        html.Div(
            "Model values: local = the local Bonsai engine, custom = "
            "your configured API. See the Engine panel guidance for how to "
            "set up custom.",
            className="canvas-ref-muted",
        )
    )

    # Sub-step flow with one textarea per prompt (requirement 1).
    for index, pk in enumerate(ordered_keys):
        block = [html.Span("%d. %s" % (index + 1, key_to_label.get(pk, pk)),
                           className="canvas-step-label")]
        block.append(
            html.Label(
                "Prompt: %s" % pk,
                className="canvas-field-label",
                htmlFor="inspector-prompt-%s" % pk,
            )
        )
        block.append(
            dcc.Textarea(
                id={"type": "inspector-prompt", "key": pk},
                value=_text(prompts[pk]),
                className="canvas-ta",
            )
        )
        fields.append(html.Div(className="canvas-field is-prompt", children=block))

    # Reference documents attached to this node (requirement 3).
    fields.append(_render_reference_list(stage_id, key))

    fields.append(
        html.Div(
            "Character count: %d" % sum(len(_text(v)) for v in prompts.values()),
            id="inspector-char-count",
            className="canvas-char-count",
            **{"aria-live": "polite"},
        )
    )
    fields.append(
        html.Button(
            "Save prompt config",
            id="inspector-save",
            n_clicks=0,
            className="canvas-save-btn",
            type="button",
        )
    )

    # Version history with one-click rollback. The config replaced by the
    # most recent save is archived in configs/history/<stage>.json.
    try:
        import prompt_history

        entries = prompt_history.load_history(key)
    except Exception:  # noqa: BLE001 - no history module, no section
        entries = []

    history_items = []
    for entry in entries[:8]:
        version = entry.get("version")
        stamp = _text(entry.get("archived_at")) or _text(entry.get("saved_at"))
        stamp_short = stamp[:16].replace("T", " ") if stamp else "-"
        history_items.append(
            html.Li(
                className="canvas-history-item",
                children=[
                    html.Span("v%s - saved %s" % (version, stamp_short),
                              className="canvas-history-label"),
                    html.Button(
                        "Roll back",
                        id={"type": "history-restore",
                            "stage": key,
                            "version": version},
                        className="btn btn-secondary",
                        n_clicks=0,
                        type="button",
                    ),
                ],
            )
        )

    fields.append(
        html.Div(
            className="canvas-history",
            children=[
                html.Span("Version history (newest first; Save archives the "
                          "previous config; Roll back restores it as a new "
                          "version):",
                          className="canvas-step-label"),
                (
                    html.Ul(id="canvas-history-list", children=history_items)
                    if history_items
                    else html.Span(
                        "No previous versions yet. Each Save archives the "
                        "config it replaces.",
                        className="canvas-ref-muted",
                    )
                ),
            ],
        )
    )
    return [html.Div(children=fields, className="canvas-inspector-inner")]


def _render_reference_list(stage_id, stage_key):
    """Render the reference-document checklist for this node (Part 1).

    One option per registered document, pre-checked from the stage's
    `references` field. The save callback reads the selected values through
    the pattern id {"type": "ref-attach", "stage": <key>, "doc": <doc key>}
    and persists them, so the boss can attach/detach the rules and reference
    documents fed to each node.
    """
    try:
        import references

        reg = references.load_registry()
        docs = reg.get("documents") or []
    except Exception:  # noqa: BLE001 - no reference module, no list
        return html.Div(className="canvas-refs")

    try:
        from prompts import find_stage_config

        store = None
        from prompts import load_store

        store = load_store()[0]
        cfg = find_stage_config(store, stage_key) if store is not None else None
        attached = list((cfg or {}).get("references") or [])
    except Exception:  # noqa: BLE001 - default to none
        attached = []

    options = []
    for doc in docs:
        dkey = doc.get("key")
        title = doc.get("title") or dkey
        loaded = bool(doc.get("loaded"))
        state = "Loaded" if loaded else "Not loaded"
        options.append(
            {"label": "%s  [%s]" % (title, state), "value": dkey}
        )

    checklist = dcc.Checklist(
        id={"type": "ref-attach", "stage": stage_key},
        options=options,
        value=[o["value"] for o in options if o["value"] in attached],
        className="canvas-ref-checklist",
        labelStyle={"display": "block"},
        inputStyle={"marginRight": "8px"},
    )

    upload_rows = []
    for doc in docs:
        dkey = doc.get("key")
        title = doc.get("title") or dkey
        loaded = bool(doc.get("loaded"))
        file_note = (
            "Loaded: %s" % os.path.basename(doc.get("file_abs"))
            if loaded
            else "No file yet"
        )
        upload_rows.append(
            html.Div(
                className="canvas-ref-upload",
                children=[
                    dcc.Upload(
                        id={"type": "ref-upload", "doc": dkey},
                        className="btn btn-secondary",
                        multiple=False,
                        children=(
                            "Replace %s" % title if loaded else "Upload %s" % title
                        ),
                    ),
                    html.Span(file_note, className="canvas-ref-muted"),
                ],
            )
        )

    return html.Div(
        className="canvas-refs",
        children=[
            html.Span("Reference documents (attach/detach per node):",
                      className="canvas-step-label"),
            checklist,
            html.Span("Load a manual with its Upload button (.txt, .md, "
                      ".pdf, or .docx); it is stored to data/reference/ "
                      "automatically. Then check it above and Save to "
                      "attach it to this node.",
                      className="canvas-ref-muted"),
            html.Div(className="canvas-ref-uploads", children=upload_rows),
        ],
    )


def _render_cancel_bar():
    """Render the Cancel control, shown only while a run is in flight."""
    run = _ACTIVE_RUN
    running = False
    if run is not None:
        try:
            running = bool(run.is_running())
        except Exception:  # noqa: BLE001 - a broken runner must not break the strip
            running = False
    if not running:
        return html.Div(id="pipe-cancel-bar", className="pipe-actionbar is-hidden")

    return html.Div(
        id="pipe-cancel-bar",
        className="pipe-actionbar",
        children=[
            html.Button(
                "Cancel run",
                id="cancel-agents",
                className="btn btn-secondary",
                n_clicks=0,
                type="button",
            ),
            html.Span(
                "Cancelling stops at the next stage boundary and keeps the "
                "findings collected so far.",
                className="pipe-actionbar-note",
            ),
        ],
    )


def _render_pipeline_region(states, selected_stage=None):
    """Render the whole pipeline window: strip, approval gate, detail, actions."""
    rows = _stage_rows(states)
    selected = _text(selected_stage)

    cards = []
    for index, row in enumerate(rows):
        if index:
            cards.append(
                html.Span(className="pipe-connector", **{"aria-hidden": "true"})
            )
        cards.append(_render_stage_card(row, selected == row["name"]))

    detail_row = None
    for row in rows:
        if row["name"] == selected:
            detail_row = row
            break
    if detail_row is None:
        detail_row = dict(EMPTY_STAGE_ROWS[0])
        detail_row["detail"] = "Select a stage card to inspect it."
        detail_row["status"] = "empty"

    return html.Div(
        id="pipeline-region",
        className="pipeline-window",
        children=[
            html.Div(
                className="pipe-head",
                children=[
                    html.H2("Review pipeline", className="panel-title"),
                    html.Div(
                        "One click runs every stage on the uploaded "
                        "manuscript with your saved prompts. Findings "
                        "stream in as stages finish.",
                        className="panel-note",
                    ),
                ],
            ),
            html.Div(
                className="pipe-strip",
                role="group",
                **{"aria-label": "Review pipeline stages"},
                children=cards,
            ),
            _render_cancel_bar(),
            _render_stage_detail(detail_row, states),
        ],
    )


def _render_ledger():
    """Render the run ledger body: newest row first, capped at LEDGER_LIMIT."""
    if not _RUN_LEDGER:
        return html.Div(
            "No stage has run yet. Upload a manuscript to start the pipeline.",
            className="board-empty",
        )

    items = []
    for entry in _RUN_LEDGER:
        status = _text(entry.get("status")) or "pending"
        if status not in STATUS_LABEL:
            status = "pending"
        started = _short_time(entry.get("started_at"))
        finished = _short_time(entry.get("finished_at"))
        stamp = started or finished or "-"
        if started and finished and finished != started:
            stamp = "%s to %s" % (started, finished)

        meta = [html.Span(stamp, className="ledger-time")]
        count = entry.get("count", 0) or 0
        if count:
            meta.append(html.Span("%s finding(s)" % count, className="ledger-count"))

        items.append(
            html.Div(
                className="ledger-item",
                children=[
                    html.Div(
                        className="ledger-head",
                        children=[
                            html.Span(
                                _text(entry.get("label")) or "Run",
                                className="ledger-stage",
                            ),
                            html.Span(
                                className="ledger-badge is-" + status,
                                children=[
                                    html.Span(
                                        className="pipe-dot", **{"aria-hidden": "true"}
                                    ),
                                    html.Span(STATUS_LABEL[status]),
                                ],
                            ),
                        ],
                    ),
                    html.Div(meta, className="ledger-meta"),
                    html.Div(_text(entry.get("detail")), className="ledger-detail"),
                ],
            )
        )

    return html.Div(className="ledger-list", children=items)


def _render_ledger_panel():
    """Render the collapsible run-ledger panel for the right column."""
    return html.Section(
        id="panel-ledger",
        className="panel",
        children=[
            html.Details(
                className="ledger-fold",
                open=True,
                children=[
                    html.Summary(
                        children=[
                            html.Span("Run ledger", className="panel-title"),
                            html.Span(
                                "Last %d stage executions" % LEDGER_LIMIT,
                                className="panel-note",
                            ),
                        ]
                    ),
                    html.Div(
                        id="ledger-list",
                        className="ledger-body",
                        children=_render_ledger(),
                    ),
                ],
            )
        ],
    )


# --------------------------------------------------------------------------
# Layout builders
# --------------------------------------------------------------------------


def _metric_block(value_id, label, value):
    return html.Div(
        className="metric-block",
        children=[
            html.Div(_text(value) or EMPTY_VALUE, id=value_id, className="metric-value"),
            html.Div(label, className="metric-label"),
        ],
    )


def _panel_a_manuscript():
    return html.Section(
        id="panel-manuscript",
        className="panel",
        children=[
            html.Div(
                className="panel-head",
                children=[
                    html.H2("Manuscript", className="panel-title"),
                    html.Div("PDF, DOCX, or TXT", className="panel-note"),
                ],
            ),
            dcc.Upload(
                id="upload-manuscript",
                className="dropzone",
                className_active="dropzone is-dragging",
                className_reject="dropzone is-rejected",
                multiple=False,
                children=html.Div(
                    className="dropzone-inner",
                    children=[
                        html.Div(
                            "Drag and drop a manuscript, or select a file",
                            className="dropzone-title",
                        ),
                        html.Div("PDF, DOCX, or TXT", className="dropzone-sub"),
                    ],
                ),
            ),
            html.Div(id="upload-filename", className="dropzone-filename"),
            html.Div(id="upload-alert"),
            html.Div(
                id="document-metrics",
                className="metric-grid",
                children=[
                    _metric_block("metric-format", "Format", EMPTY_VALUE),
                    _metric_block("metric-pages", "Pages", EMPTY_VALUE),
                    _metric_block("metric-words", "Words", EMPTY_VALUE),
                    _metric_block("metric-characters", "Characters", EMPTY_VALUE),
                ],
            ),
            html.Div(
                id="preview-region",
                className="preview",
                children=html.Div(
                    "No manuscript loaded yet.",
                    className="preview-empty",
                    id="preview-empty",
                ),
            ),
        ],
    )


def _panel_b_review():
    return html.Section(
        id="panel-review",
        className="panel",
        children=[
            html.Div(
                className="panel-head",
                children=[
                    html.H2("Review", className="panel-title"),
                    html.Div(id="review-count", className="panel-note"),
                ],
            ),
            dcc.Checklist(
                id="review-options",
                className="checklist-row",
                options=[
                    {"label": "Citation review (LLM pass)", "value": "citation"},
                    {"label": "APA 7 style (LLM pass)", "value": "apa7"},
                    {"label": "Army publication standards (LLM pass)", "value": "army"},
                ],
                value=["citation", "apa7", "army"],
            ),
            html.Div(
                className="btn-row",
                children=[
                    html.Button(
                        "Run review",
                        id="run-review",
                        className="btn btn-primary",
                        n_clicks=0,
                        type="button",
                    ),
                    html.Button(
                        "Export summary letter",
                        id="export-summary",
                        className="btn btn-secondary",
                        n_clicks=0,
                        type="button",
                    ),
                    dcc.Download(id="download-summary"),
                ],
            ),
            html.Div(
                id="review-alert",
                children=[],
            ),
            html.Div(
                id="findings-board",
                className="board",
                children=[
                    html.Div(
                        className="filter-row",
                        children=[
                            html.Button(
                                "All",
                                id="filter-all",
                                className="chip is-active",
                                n_clicks=0,
                                type="button",
                            ),
                            html.Button(
                                "Errors",
                                id="filter-errors",
                                className="chip",
                                n_clicks=0,
                                type="button",
                            ),
                            html.Button(
                                "Warnings",
                                id="filter-warnings",
                                className="chip",
                                n_clicks=0,
                                type="button",
                            ),
                        ],
                    ),
                    html.Div(
                        id="findings-list",
                        className="findings-list",
                        children=html.Div(
                            "No review has been run yet. Upload a manuscript and select Run review.",
                            className="board-empty",
                        ),
                    ),
                ],
            ),
        ],
    )


def _kv_row(label, value_id, value):
    return html.Div(
        className="kv-row",
        children=[
            html.Span(label, className="kv-key"),
            html.Span(_text(value) or EMPTY_VALUE, id=value_id, className="kv-value"),
        ],
    )


def _custom_api_guidance():
    """The collapsed "how to connect your own API" note (Part 2).

    A placeholder section (delimited by HOPOVER-DOCS markers) is reserved for
    the vendor/plugin documentation the boss will paste later. All ASCII.
    """
    return html.Details(
        className="api-guidance",
        children=[
            html.Summary("How to connect your own API (plugin / util config)"),
            html.Div(
                className="api-guidance-body",
                children=[
                    html.Ol(
                        children=[
                            html.Li(
                                "What the Custom outlet is: any OpenAI-compatible "
                                "endpoint (AskSage, an internal gateway, a Foundry "
                                "proxy, or any other service that speaks /v1/chat/..."
                                ")."
                            ),
                            html.Li(
                                "It needs exactly three values: a Base URL ending "
                                "in /v1, the exact Model name the endpoint reports, "
                                "and the API key."
                            ),
                            html.Li(
                                "Set them in configs/.env: CUSTOM_API_BASE, "
                                "CUSTOM_MODEL, CUSTOM_API_KEY. Environment "
                                "variables override the file; restart the "
                                "dashboard after editing."
                            ),
                            html.Li(
                                "Verify: switch Provider to Custom API, click Test "
                                "connection (green pill = reachable), then run one "
                                "stage."
                            ),
                            html.Li(
                                "Fallback: when the local Bonsai engine is down and the Custom "
                                "outlet is fully configured, the client retries "
                                "through Custom automatically."
                            ),
                            html.Li(
                                "Per node: each review node's Model field in the "
                                "prompt editor takes local (Bonsai) or custom "
                                "(your API)."
                            ),
                        ]
                    ),
                    html.Div(
                        "HOPOVER-DOCS-START\n"
                        "Paste the vendor / plugin / util documentation here. It "
                        "will be merged into this note without restructuring.\n"
                        "HOPOVER-DOCS-END",
                        className="api-guidance-placeholder",
                    ),
                ],
            ),
        ],
    )


def _panel_c_engine():
    local = _provider_config("local")
    return html.Section(
        id="panel-engine",
        className="panel",
        children=[
            html.Div(
                className="panel-head",
                children=[html.H2("Engine", className="panel-title")],
            ),
            html.Label("Provider", className="field-label", htmlFor="provider-local"),
            html.Div(
                className="segmented",
                role="group",
                **{"aria-label": "Provider"},
                children=[
                    html.Button(
                        "Local (Bonsai)",
                        id="provider-local",
                        className="segmented-btn is-active",
                        n_clicks=0,
                        type="button",
                    ),
                    html.Button(
                        "Custom API",
                        id="provider-custom",
                        className="segmented-btn",
                        n_clicks=0,
                        type="button",
                    ),
                ],
            ),
            _custom_api_guidance(),
            html.Div(
                className="btn-row",
                children=[
                    html.Button(
                        "Test connection",
                        id="test-connection",
                        className="btn btn-secondary",
                        n_clicks=0,
                        type="button",
                    )
                ],
            ),
            html.Div(id="engine-alert"),
            html.Div(
                id="engine-kv",
                className="kv-list",
                children=[
                    _kv_row("Provider", "kv-provider", local["label"]),
                    _kv_row("Model", "kv-model", local["model"]),
                    _kv_row("Endpoint", "kv-endpoint", local["endpoint"]),
                    _kv_row("Fallback", "kv-fallback", local["fallback"]),
                ],
            ),
        ],
    )


def _panel_d_playground():
    return html.Section(
        id="panel-playground",
        className="panel",
        children=[
            html.Div(
                className="panel-head",
                children=[
                    html.H2("Playground", className="panel-title"),
                    html.Div(
                        "Free-form question to the engine. For the full "
                        "manuscript review, use Run review on the left.",
                        className="panel-note",
                    ),
                ],
            ),
            dcc.Textarea(
                id="prompt-input",
                className="prompt-input",
                placeholder="Ask the model anything about the manuscript.",
                value="",
            ),
            html.Div(
                className="btn-row",
                children=[
                    html.Button(
                        "Run prompt",
                        id="run-prompt",
                        className="btn btn-primary",
                        n_clicks=0,
                        type="button",
                    )
                ],
            ),
            html.Div(
                "Runs against the selected engine. If it reports offline, "
                "click Test connection, then run again.",
                id="playground-hint",
                className="hint",
            ),
            html.Div(id="playground-alert"),
            html.Div(
                id="playground-response",
                children=[
                    html.Div(
                        className="response-card",
                        children=[
                            html.Div(
                                "Playground",
                                className="response-badge",
                                id="response-badge",
                            ),
                            html.Div(
                                "Ask a question about the manuscript, then "
                                "select Run prompt. For the full review of "
                                "the uploaded manuscript, use Run review on "
                                "the left.",
                                className="response-text",
                                id="response-text",
                            ),
                        ],
                    )
                ],
            ),
            # Loading state for a prompt in flight. Hidden until it is needed.
            html.Div(
                id="playground-loading",
                className="skeleton-group",
                style={"display": "none"},
                children=[
                    html.Div(className="skeleton is-title"),
                    html.Div(className="skeleton is-full"),
                    html.Div(className="skeleton is-medium"),
                ],
            ),
        ],
    )


def build_layout():
    """Compose the full single-page layout."""
    return html.Div(
        className="app-root",
        children=[
            # Loading states for the two long-running regions. Hidden until a
            # callback reveals them, then shaped like the content they replace.
            html.Div(
                id="layout-loading",
                style={"display": "none"},
                children=[
                    html.Div(
                        id="loading-review",
                        className="skeleton-group",
                        children=[
                            html.Div(className="skeleton is-title"),
                            html.Div(className="skeleton is-full"),
                            html.Div(className="skeleton is-medium"),
                            html.Div(className="skeleton is-short"),
                        ],
                    ),
                    html.Div(
                        id="loading-upload",
                        className="skeleton-group",
                        children=[
                            html.Div(className="skeleton is-title"),
                            html.Div(
                                className="metric-grid",
                                children=[
                                    html.Div(className="skeleton is-metric"),
                                    html.Div(className="skeleton is-metric"),
                                    html.Div(className="skeleton is-metric"),
                                    html.Div(className="skeleton is-metric"),
                                ],
                            ),
                            html.Div(className="skeleton is-block"),
                        ],
                    ),
                ],
            ),
            html.Header(
                className="brandbar",
                children=[
                    html.Div(
                        className="brandbar-inner",
                        children=[
                            html.Div(
                                className="brand-lockup",
                                children=[
                                    html.Div("AskSage Proof Agent", className="brand-wordmark"),
                                    html.Div(
                                        "Manuscript review | APA 7 & Army publication standards",
                                        className="brand-tagline",
                                    ),
                                ],
                            ),
                            _status_pill("untested", "Untested"),
                        ],
                    )
                ],
            ),
            # Goal 3: Agent Builder canvas. Sits directly above the list
            # strip; the strip stays in the DOM underneath as list mode.
            # Pipeline strip. Sits between the brand bar and the two-column
            # grid so the whole seven-stage flow is visible at a glance.
            _render_pipeline_region(None, None),
            html.Main(
                className="page",
                children=[
                    html.Div(
                        className="layout-grid",
                        children=[
                            html.Div(
                                className="col-left",
                                children=[_panel_a_manuscript(), _panel_b_review()],
                            ),
                            html.Div(
                                className="col-right",
                                children=[
                                    _render_ledger_panel(),
                                    _panel_c_engine(),
                                    _panel_d_playground(),
                                ],
                            ),
                        ],
                    )
                ],
            ),
            html.Footer(
                className="footer",
                children=html.Div(FOOTER_TEXT, className="footer-inner"),
            ),
            # Client-side state
            dcc.Store(id="store-document", storage_type="memory"),
            dcc.Store(id="store-findings", storage_type="memory"),
            dcc.Store(id="store-provider", storage_type="memory", data={"provider": "local"}),
            dcc.Store(id="store-connection", storage_type="memory", data={"state": "untested", "label": "Untested"}),
            # Pipeline state as a serialized to_dict() snapshot, plus the
            # stage the detail panel is currently showing.
            dcc.Store(id="store-pipeline", storage_type="memory"),
            dcc.Store(id="store-selected-stage", storage_type="memory"),
            # The inspected stage and the prompts snapshot cache. Memory
            # stores so a refresh resets the session.
            dcc.Store(id="store-inspector-stage", storage_type="memory"),
            dcc.Store(id="store-prompts-cache", storage_type="memory"),
            # One polling clock for the whole pipeline. It stays disabled
            # until an agent run starts, so an idle page makes no requests.
            dcc.Interval(id="pip-progress", interval=1000, disabled=True),
        ],
    )


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------

app = Dash(__name__, suppress_callback_exceptions=True, title="AskSage Proof Agent")
app.layout = build_layout()


@app.server.route("/health")
def health():
    """Liveness probe used by the container orchestration."""
    return {"status": "ok"}, 200


# --------------------------------------------------------------------------
# Callbacks
# --------------------------------------------------------------------------


@app.callback(
    Output("store-document", "data"),
    Output("metric-format", "children"),
    Output("metric-pages", "children"),
    Output("metric-words", "children"),
    Output("metric-characters", "children"),
    Output("preview-region", "children"),
    Output("upload-filename", "children"),
    Output("upload-alert", "children"),
    Output("loading-upload", "style"),
    Input("upload-manuscript", "contents"),
    State("upload-manuscript", "filename"),
    prevent_initial_call=True,
)
def upload_parse(contents, filename):
    """Save the upload under data/, parse it, and fill the overview and preview."""
    empty_metrics = (EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE)
    hidden = {"display": "none"}
    try:
        if not contents:
            return (
                no_update,
                *empty_metrics,
                html.Div("No manuscript loaded yet.", className="preview-empty"),
                "",
                [],
                hidden,
            )

        safe_name = _safe_name(filename)
        os.makedirs(DATA_DIR, exist_ok=True)
        target = os.path.join(DATA_DIR, safe_name)

        _, _, payload = contents.partition(",")
        raw = base64.b64decode(payload)
        with open(target, "wb") as handle:
            handle.write(raw)

        try:
            from document_parser import DocumentParser  # lazy: backend may be absent
        except ImportError as exc:
            return (
                no_update,
                *empty_metrics,
                html.Div("No manuscript loaded yet.", className="preview-empty"),
                safe_name,
                _alert(
                    "Document parser unavailable",
                    "The file was saved to data/%s but could not be read: %s" % (safe_name, exc),
                    "Install the parser dependencies and upload the file again.",
                ),
                hidden,
            )

        parsed = DocumentParser().parse(target)
        text = _text(parsed.get("text") if isinstance(parsed, dict) else parsed)
        metadata = parsed.get("metadata", {}) if isinstance(parsed, dict) else {}
        fmt = _text(metadata.get("format") or os.path.splitext(safe_name)[1].lstrip(".")).upper() or EMPTY_VALUE
        pages = parsed.get("total_pages") if isinstance(parsed, dict) else None
        if pages is None:
            pages = metadata.get("total_pages", metadata.get("total_lines", EMPTY_VALUE))

        words = len(text.split())
        characters = len(text)

        document = {
            "name": safe_name,
            "path": target,
            "text": text,
            "format": fmt,
            "pages": _text(pages) or EMPTY_VALUE,
            "words": words,
            "characters": characters,
        }

        preview_children = (
            html.Pre(text[:20000], className="preview-text")
            if text.strip()
            else html.Div("No manuscript loaded yet.", className="preview-empty")
        )

        return (
            document,
            fmt,
            _text(pages) or EMPTY_VALUE,
            "{:,}".format(words),
            "{:,}".format(characters),
            preview_children,
            safe_name,
            [],
            hidden,
        )
    except Exception as exc:  # noqa: BLE001 - render the error state instead of raising
        _log("upload_parse failed: %s" % traceback.format_exc().splitlines()[-1])
        return (
            no_update,
            *empty_metrics,
            html.Div("No manuscript loaded yet.", className="preview-empty"),
            "",
            _alert(
                "Upload failed",
                "The file could not be read: %s" % exc,
                "Confirm the file is a valid PDF, DOCX, or TXT and try again.",
            ),
            hidden,
        )


@app.callback(
    Output("store-pipeline", "data", allow_duplicate=True),
    Output("pipeline-region", "children", allow_duplicate=True),
    Output("pip-progress", "disabled"),
    Output("review-alert", "children", allow_duplicate=True),
    Output("loading-review", "style"),
    Input("run-review", "n_clicks"),
    State("review-options", "value"),
    State("store-document", "data"),
    State("store-pipeline", "data"),
    State("store-provider", "data"),
    prevent_initial_call=True,
)
def run_review(n_clicks, options, document, states, provider):
    """Run the full pipeline on the uploaded manuscript in one click.

    The deterministic scan already ran at upload; this starts the selected
    stages - including the LLM passes - on the engine, using each stage's
    saved prompts, outlet, temperature, and token budget. Findings stream
    into the board through the progress ticker as stages finish.
    """
    global _ACTIVE_RUN
    hidden = {"display": "none"}
    try:
        if not n_clicks:
            return (no_update,) * 5

        text = _text((document or {}).get("text"))
        if not text.strip():
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                _alert(
                    "No manuscript loaded",
                    "A review needs manuscript text to check.",
                    "Upload a PDF, DOCX, or TXT file in the Manuscript panel first.",
                ),
                hidden,
            )

        options_set = set(options or [])
        selected_stages = ["s1_extract", "s2_cross_section"]
        if "citation" in options_set:
            selected_stages.append("s3_citations")
        if "apa7" in options_set:
            selected_stages.append("s4_sme")
        if "army" in options_set:
            selected_stages.append("s5_copyedit")
        selected_stages.extend(["s6_dedup", "s7_report"])

        provider_key = _provider_key(provider)
        config = _provider_config(provider_key)
        client, error = _build_llm_client(provider_key)
        if client is None:
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                _alert(
                    "Engine unavailable",
                    error,
                    "Select Test connection in the Engine panel, then run again.",
                ),
                hidden,
            )

        try:
            from runner import ReviewRun
        except ImportError as exc:
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                _alert(
                    "Runner unavailable",
                    "The background review runner is not importable: %s" % exc,
                    "Confirm src/runner.py is present, then try again.",
                ),
                hidden,
            )

        try:
            import outlets as outlets_mod
        except ImportError:
            outlets_mod = None

        run = ReviewRun(
            client,
            selected=selected_stages,
            client_factory=(outlets_mod.build_client if outlets_mod else None),
        )
        run.start(text)
        _ACTIVE_RUN = run

        try:
            from pipeline import PipelineState

            state = PipelineState()
            for stage_name in selected_stages:
                state.set_status(stage_name, "pending", "queued by Run review")
            snapshot = state.to_dict()
        except Exception:  # noqa: BLE001 - strip rendering must not block the run
            snapshot = states

        _ledger_add(
            "run",
            "running",
            0,
            "started %d stage(s) on %s" % (len(selected_stages), config["label"]),
        )

        return (
            snapshot,
            _render_pipeline_region(snapshot, None),
            False,
            [],
            hidden,
        )
    except Exception as exc:  # noqa: BLE001 - render the error state instead of raising
        _log("run_review failed: %s" % traceback.format_exc().splitlines()[-1])
        return (
            no_update,
            _render_pipeline_region(states, None),
            no_update,
            _alert(
                "Review failed",
                "The review could not be started: %s" % exc,
                "Try again, or check the engine configuration in the Engine panel.",
            ),
            hidden,
        )


@app.callback(
    Output("findings-list", "children", allow_duplicate=True),
    Output("filter-all", "className"),
    Output("filter-errors", "className"),
    Output("filter-warnings", "className"),
    Input("filter-all", "n_clicks"),
    Input("filter-errors", "n_clicks"),
    Input("filter-warnings", "n_clicks"),
    State("store-findings", "data"),
    prevent_initial_call=True,
)
def filter_findings(all_clicks, error_clicks, warning_clicks, findings):
    """Filter the stored findings by the selected chip."""
    try:
        selected, active_id = _triggered_chip()
        classes = {}
        for chip_id in ("filter-all", "filter-errors", "filter-warnings"):
            classes[chip_id] = "chip is-active" if chip_id == active_id else "chip"

        return (
            _findings_view(findings or [], selected),
            classes["filter-all"],
            classes["filter-errors"],
            classes["filter-warnings"],
        )
    except Exception as exc:  # noqa: BLE001 - render the error state instead of raising
        _log("filter_findings failed: %s" % traceback.format_exc().splitlines()[-1])
        return (
            html.Div(
                "The findings list could not be filtered. Select All to reset the view.",
                className="board-empty",
            ),
            "chip is-active",
            "chip",
            "chip",
        )


@app.callback(
    Output("download-summary", "data"),
    Input("export-summary", "n_clicks"),
    State("store-document", "data"),
    State("store-findings", "data"),
    State("store-provider", "data"),
    prevent_initial_call=True,
)
def export_summary(n_clicks, document, findings, provider):
    """Download the review summary letter as Markdown."""
    try:
        if not n_clicks:
            return no_update

        provider_key = (provider or {}).get("provider", "local")
        metrics = {}
        if document:
            metrics = {
                "format": document.get("format", EMPTY_VALUE),
                "pages": document.get("pages", EMPTY_VALUE),
                "words": document.get("words", EMPTY_VALUE),
                "characters": document.get("characters", EMPTY_VALUE),
            }
        markdown = _summary_markdown(
            (document or {}).get("name", ""),
            metrics,
            findings or [],
            _provider_config(provider_key)["label"],
            provider_key,
        )
        # dcc.Download is a wildcard output, so the payload must be returned
        # as a single-element list rather than a bare dict.
        return [dcc.send_string(markdown, "review-summary.md")]
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("export_summary failed: %s" % traceback.format_exc().splitlines()[-1])
        return no_update


@app.callback(
    Output("store-provider", "data"),
    Output("provider-local", "className"),
    Output("provider-custom", "className"),
    Output("kv-provider", "children"),
    Output("kv-model", "children"),
    Output("kv-endpoint", "children"),
    Output("kv-fallback", "children"),
    Output("store-connection", "data"),
    Output("status-pill", "className"),
    Output("status-text", "children"),
    Output("run-prompt", "disabled"),
    Output("playground-hint", "children"),
    Input("provider-local", "n_clicks"),
    Input("provider-custom", "n_clicks"),
    prevent_initial_call=True,
)
def switch_provider(local_clicks, custom_clicks):
    """Toggle the segmented control and republish the engine key-value rows."""
    try:
        triggered = None
        try:
            from dash import ctx

            triggered = ctx.triggered_id
        except Exception:  # noqa: BLE001 - fall back to the local provider
            triggered = None

        provider_key = "custom" if triggered == "provider-custom" else "local"
        config = _provider_config(provider_key)

        classes = {
            "local": "segmented-btn is-active" if provider_key == "local" else "segmented-btn",
            "custom": "segmented-btn is-active" if provider_key == "custom" else "segmented-btn",
        }

        # Switching provider resets the connection state: the new engine is untested.
        connection = {"state": "untested", "label": "Untested"}

        return (
            {"provider": provider_key},
            classes["local"],
            classes["custom"],
            config["label"],
            config["model"] or EMPTY_VALUE,
            config["endpoint"] or EMPTY_VALUE,
            config["fallback"],
            connection,
            "status-pill is-untested",
            "Untested",
            False,
            "Runs against the selected engine. If it reports offline, "
            "click Test connection, then run again.",
        )
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("switch_provider failed: %s" % traceback.format_exc().splitlines()[-1])
        return (no_update,) * 12


@app.callback(
    Output("store-connection", "data", allow_duplicate=True),
    Output("status-pill", "className", allow_duplicate=True),
    Output("status-text", "children", allow_duplicate=True),
    Output("engine-alert", "children"),
    Output("run-prompt", "disabled", allow_duplicate=True),
    Output("playground-hint", "children", allow_duplicate=True),
    Output("response-badge", "children", allow_duplicate=True),
    Output("response-text", "children", allow_duplicate=True),
    Input("test-connection", "n_clicks"),
    State("store-provider", "data"),
    prevent_initial_call=True,
)
def connect_test(n_clicks, provider):
    """Probe the selected engine and publish the status pill. Never crashes.

    The response card is also refreshed here: leaving the static
    "No provider / No prompt has been run yet." placeholders visible while
    the pill says connected read as contradictory.
    """
    try:
        if not n_clicks:
            return (no_update,) * 8

        provider_key = _provider_key(provider)
        config = _provider_config(provider_key)

        response, error = _call_llm(
            provider_key,
            "Reply with the single word: ready",
            system_prompt="You are a connection probe. Answer with one word.",
        )

        if error:
            return (
                {"state": "offline", "label": "Offline"},
                "status-pill is-offline",
                "Offline",
                _alert(
                    "Engine offline",
                    error,
                    "Confirm the endpoint is reachable, then select Test connection again.",
                ),
                False,
                "The engine did not answer. Run prompt probes again on click.",
                "Not connected",
                "No engine answered. Test the connection, then run a prompt.",
            )

        label = config["model"] or config["label"]
        return (
            {"state": "connected", "label": label},
            "status-pill is-connected",
            label,
            [],
            False,
            "Engine connected. Prompts run against %s." % config["label"],
            config["label"],
            "Connected to %s. Ask a question about the manuscript and "
            "select Run prompt." % label,
        )
    except Exception as exc:  # noqa: BLE001 - the pill must always render
        _log("connect_test failed: %s" % traceback.format_exc().splitlines()[-1])
        return (
            {"state": "offline", "label": "Offline"},
            "status-pill is-offline",
            "Offline",
            _alert(
                "Connection test failed",
                "The connection test could not run: %s" % exc,
                "Check the engine configuration and try again.",
            ),
            False,
            "The engine did not answer. Run prompt probes again on click.",
            "Not connected",
            "No engine answered. Test the connection, then run a prompt.",
        )


@app.callback(
    Output("response-badge", "children"),
    Output("response-text", "children"),
    Output("playground-alert", "children"),
    Output("playground-loading", "style"),
    Input("run-prompt", "n_clicks"),
    State("prompt-input", "value"),
    State("store-provider", "data"),
    State("store-connection", "data"),
    State("store-document", "data"),
    prevent_initial_call=True,
)
def run_prompt(n_clicks, prompt, provider, connection, document):
    """Send the playground prompt to the selected engine."""
    hidden = {"display": "none"}
    try:
        if not n_clicks:
            return (no_update,) * 4

        provider_key = _provider_key(provider)
        config = _provider_config(provider_key)

        if (connection or {}).get("state") != "connected":
            # The operator may have skipped Test connection. Probe once
            # inline; proceed only when the engine actually answers.
            _probe, probe_error = _call_llm(
                provider_key,
                "Reply with the single word: ready",
                system_prompt="You are a connection probe. Answer with one word.",
            )
            if probe_error:
                return (
                    "Not connected",
                    "No response yet.",
                    _alert(
                        "Engine not connected",
                        probe_error,
                        "Select Test connection in the Engine panel, then run the prompt.",
                    ),
                    hidden,
                )

        question = _text(prompt).strip()
        if not question:
            return (
                config["label"],
                "No response yet.",
                _alert(
                    "Empty prompt",
                    "The prompt box is empty, so nothing was sent.",
                    "Type a question about the manuscript and select Run prompt.",
                ),
                hidden,
            )

        context = _text((document or {}).get("text"))[:4000]
        full_prompt = question
        if context.strip():
            full_prompt = (
                "Manuscript excerpt follows. Use it as context.\n\n"
                "%s\n\nQuestion: %s" % (context, question)
            )

        response, error = _call_llm(
            provider_key,
            full_prompt,
            system_prompt=(
                "You are a manuscript review assistant working to APA 7 and "
                "Army publication standards. Answer in plain English."
            ),
        )

        if error:
            return (
                config["label"],
                "No response yet.",
                _alert(
                    "Prompt failed",
                    error,
                    "Check the engine endpoint, then select Test connection and try again.",
                ),
                hidden,
            )

        return (
            config["label"],
            response or "The engine returned an empty response.",
            [],
            hidden,
        )
    except Exception as exc:  # noqa: BLE001 - render the error state instead of raising
        _log("run_prompt failed: %s" % traceback.format_exc().splitlines()[-1])
        return (
            "Error",
            "No response yet.",
            _alert(
                "Prompt failed",
                "The prompt could not be completed: %s" % exc,
                "Try again, or check the engine configuration in the Engine panel.",
            ),
            hidden,
        )


# --------------------------------------------------------------------------
# Loading states
#
# The skeleton markup is rendered in the layout and hidden with an inline
# style. It is flipped visible while a long callback is in flight and hidden
# again when the callback returns, which keeps the loading state to a single
# output per callback instead of a second round trip.
# --------------------------------------------------------------------------


@app.callback(
    Output("loading-review", "style"),
    Input("run-review", "n_clicks"),
    prevent_initial_call=True,
)
def show_review_loading(n_clicks):
    """Reveal the findings skeleton while the review runs.

    The style must be a plain dict: a list-wrapped style crashes React
    ("indexed property on CSSStyleDeclaration") and the whole update is
    dropped, which made responses never render.
    """
    try:
        if not n_clicks:
            return no_update
        return {"display": "block"}
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("show_review_loading failed: %s" % exc)
        return {"display": "none"}


@app.callback(
    Output("loading-upload", "style"),
    Input("upload-manuscript", "contents"),
    prevent_initial_call=True,
)
def show_upload_loading(contents):
    """Reveal the metrics skeleton while the upload is parsed."""
    try:
        if not contents:
            return no_update
        return {"display": "block"}
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("show_upload_loading failed: %s" % exc)
        return {"display": "none"}


@app.callback(
    Output("playground-loading", "style"),
    Input("run-prompt", "n_clicks"),
    State("store-connection", "data"),
    prevent_initial_call=True,
)
def show_prompt_loading(n_clicks, connection):
    """Reveal the response skeleton while a prompt runs."""
    try:
        if not n_clicks:
            return no_update
        if (connection or {}).get("state") != "connected":
            return {"display": "none"}
        return {"display": "block"}
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("show_prompt_loading failed: %s" % exc)
        return {"display": "none"}


# --------------------------------------------------------------------------
# Pipeline callbacks
#
# The seven-stage strip is driven by PipelineState. The deterministic rules
# pass runs inside the upload flow (through the existing _call_review_engine
# path); the three LLM agent passes run on the runner's daemon thread and are
# polled by the single dcc.Interval below.
#
# Every callback here is defensive: a missing document, a missing runner, or
# a malformed snapshot renders a static strip instead of raising.
# --------------------------------------------------------------------------


def _pipeline_outputs(states, selected=None):
    """Return the (store-pipeline, pipeline-region) pair for a snapshot."""
    return states, _render_pipeline_region(states, selected)


def _finding_key(finding):
    """Build the dedupe key for a finding dict."""
    return (
        _text(finding.get("agent")).lower(),
        _text(finding.get("location")).lower(),
        _text(finding.get("issue")).lower(),
    )


def _merge_findings(existing, incoming):
    """Append incoming findings to existing ones, skipping duplicates.

    The deterministic rules findings are always kept first; agent findings
    are appended after them in the order the runner produced them.
    """
    merged = list(existing or [])
    seen = set()
    for item in merged:
        if isinstance(item, dict):
            seen.add(_finding_key(item))
    for item in incoming or []:
        if not isinstance(item, dict):
            continue
        key = _finding_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _findings_count_label(findings):
    """Return the "N findings" label for the review panel head."""
    count = len(findings or [])
    return "%d finding%s" % (count, "" if count == 1 else "s")


def _agent_findings(run, provider_label):
    """Collect the runner's findings, normalized and provenance-tagged.

    The runner returns the raw finding schema (agent, severity, location,
    original_text, issue, suggested_fix, source). Each finding is normalized
    onto the keys the cards render and tagged with the agent and the model
    that produced it, so the board shows where every finding came from.
    """
    collected = []
    if run is None:
        return collected
    try:
        result = run.result()
    except Exception as exc:  # noqa: BLE001 - a broken runner yields no findings
        _log("runner result failed: %s" % exc)
        return collected

    for stage_name, payload in (result or {}).items():
        if not isinstance(payload, dict):
            continue
        persona = STAGE_PERSONA.get(stage_name, stage_name)
        for item in payload.get("findings", []) or []:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_finding(item)
            normalized["agent"] = _text(item.get("agent")) or persona
            normalized["provenance"] = "%s agent / %s" % (persona, provider_label)
            collected.append(normalized)
    return collected


def _ledger_from_pipeline(states):
    """Append one ledger row per stage that has finished since it last ran."""
    for row in _stage_rows(states):
        status = row["status"]
        if status not in TERMINAL_STATUS:
            continue
        key = (row["name"], status, _text(row.get("finished_at")))
        if key in _LEDGER_SEEN:
            continue
        _LEDGER_SEEN.add(key)
        _ledger_add(
            row["name"],
            status,
            row.get("count", 0),
            row.get("detail"),
            row.get("started_at"),
            row.get("finished_at"),
        )


#: Ledger rows already written, so a polled snapshot never double-logs.
_LEDGER_SEEN = set()


@app.callback(
    Output("store-pipeline", "data"),
    Output("pipeline-region", "children"),
    Output("store-findings", "data", allow_duplicate=True),
    Output("findings-list", "children", allow_duplicate=True),
    Output("review-count", "children", allow_duplicate=True),
    Output("review-alert", "children", allow_duplicate=True),
    Output("ledger-list", "children"),
    Input("store-document", "data"),
    prevent_initial_call=True,
)
def pipeline_after_upload(document):
    """Run the deterministic rules pass and open the human approval gate.

    This is the gate the whole pipeline hangs on: upload, parse, and rules
    all complete here, the rule findings are published to the board
    immediately, and the three agent stages are parked in
    "awaiting_approval" until a human approves them.
    """
    global _LAST_DOC, _ACTIVE_RUN, _AGENT_SELECTION

    try:
        text = _text((document or {}).get("text"))
        if not document or not text.strip():
            # An empty upload is not an error: leave the strip untouched.
            return (no_update,) * 7

        if _LAST_DOC == document:
            # The same manuscript was already processed; do not re-run the
            # rules pass on every unrelated store refresh.
            return (no_update,) * 7

        _LAST_DOC = document
        _ACTIVE_RUN = None
        _AGENT_SELECTION = {"s3_citations": True, "s4_sme": True, "s5_copyedit": True}
        _LEDGER_SEEN.clear()
        _RUN_LEDGER.clear()

        state = _pipeline_state()
        if state is None:
            return (no_update,) * 7

        state.set_status("s1_extract", "done", _text(document.get("name")) or "1 file")
        state.set_count("s1_extract", 1)
        state.set_status(
            "s2_cross_section",
            "done",
            "%s, %s page(s), %s word(s)"
            % (
                _text(document.get("format")) or EMPTY_VALUE,
                _text(document.get("pages")) or EMPTY_VALUE,
                "{:,}".format(int(document.get("words", 0) or 0)),
            ),
        )
        state.set_count("s2_cross_section", 1)

        findings, error = _call_review_engine(
            text, ["citation", "apa7", "army"]
        )
        if error:
            state.set_status("s2_cross_section", "failed", error)
            state.set_count("s2_cross_section", 0)
            alert = _alert(
                "Rules pass unavailable",
                error,
                "The strip keeps the gate closed until the rules pass succeeds.",
            )
            findings = []
        else:
            findings = findings or []
            state.set_status(
                "s2_cross_section",
                "done",
                "%d rule hit%s from the deterministic checks"
                % (len(findings), "" if len(findings) == 1 else "s"),
            )
            state.set_count("s2_cross_section", len(findings))
            alert = []

        for stage_name in ("s3_citations", "s4_sme", "s5_copyedit"):
            state.set_status(stage_name, "awaiting_approval", "awaiting user approval")

        snapshot = state.to_dict()
        _ledger_from_pipeline(snapshot)

        return (
            snapshot,
            _render_pipeline_region(snapshot, None),
            findings,
            _findings_view(findings, "all"),
            _findings_count_label(findings),
            alert,
            _render_ledger(),
        )
    except Exception as exc:  # noqa: BLE001 - render the error state instead of raising
        _log("pipeline_after_upload failed: %s" % traceback.format_exc().splitlines()[-1])
        return (
            no_update,
            _render_pipeline_region(None, None),
            no_update,
            no_update,
            no_update,
            _alert(
                "Pipeline could not start",
                "The deterministic rules pass could not run: %s" % exc,
                "Upload the manuscript again, or check the review engine.",
            ),
            _render_ledger(),
        )


@app.callback(
    Output("store-pipeline", "data", allow_duplicate=True),
    Output("pipeline-region", "children", allow_duplicate=True),
    Output("pip-progress", "disabled"),
    Output("pipe-estimate", "children", allow_duplicate=True),
    Output("review-alert", "children", allow_duplicate=True),
    Input("run-agents", "n_clicks"),
    State("agent-toggle", "value"),
    State("store-document", "data"),
    State("store-pipeline", "data"),
    State("store-provider", "data"),
    prevent_initial_call=True,
)
def run_selected_agents(n_clicks, selected, document, states, provider):
    """Start the approved agent passes on the runner's daemon thread."""
    global _ACTIVE_RUN

    try:
        if not n_clicks:
            return (no_update,) * 5

        text = _text((document or {}).get("text"))
        if not text.strip():
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                no_update,
                _alert(
                    "No manuscript loaded",
                    "The agent passes need manuscript text to review.",
                    "Upload a PDF, DOCX, or TXT file in the Manuscript panel first.",
                ),
            )

        selected_stages = [
            PERSONA_STAGE[name]
            for name in ("citation", "apa", "sme")
            if name in (selected or []) and name in PERSONA_STAGE
        ]
        if not selected_stages:
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                no_update,
                _alert(
                    "No agent selected",
                    "Every agent toggle is off, so nothing was started.",
                    "Select at least one agent and run the selected agents again.",
                ),
            )

        provider_key = (provider or {}).get("provider", "local")
        config = _provider_config(provider_key)
        client, error = _build_llm_client(provider_key)
        if client is None:
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                no_update,
                _alert(
                    "Engine unavailable",
                    error or "No LLM client could be constructed.",
                    "Check the engine configuration in the Engine panel, then try again.",
                ),
            )

        state = _pipeline_from_states(states)
        if state is None:
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                no_update,
                _alert(
                    "Runner unavailable",
                    "The pipeline state machine could not be loaded.",
                    "Confirm src/pipeline.py is present, then try again.",
                ),
            )

        try:
            from runner import ReviewRun
        except ImportError as exc:
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                no_update,
                _alert(
                    "Runner unavailable",
                    "The background review runner is not importable: %s" % exc,
                    "Confirm src/runner.py is present, then try again.",
                ),
            )

        try:
            import outlets as outlets_mod
        except ImportError:
            outlets_mod = None
        run = ReviewRun(
            client,
            selected=selected_stages,
            pipeline=state,
            client_factory=(outlets_mod.build_client if outlets_mod else None),
        )
        run.start(text)
        _ACTIVE_RUN = run

        _ledger_add(
            "run",
            "running",
            0,
            "started %s stage(s) on %s" % (len(selected_stages), config["label"]),
        )

        snapshot = state.to_dict()
        return (
            snapshot,
            _render_pipeline_region(snapshot, None),
            False,
            "Running %d stage(s) on the local model." % len(selected_stages),
            [],
        )
    except Exception as exc:  # noqa: BLE001 - render the error state instead of raising
        _log("run_selected_agents failed: %s" % traceback.format_exc().splitlines()[-1])
        return (
            no_update,
            _render_pipeline_region(states, None),
            no_update,
            no_update,
            _alert(
                "Agent run failed to start",
                "The agent passes could not be started: %s" % exc,
                "Try again, or check the engine configuration in the Engine panel.",
            ),
        )


@app.callback(
    Output("store-pipeline", "data", allow_duplicate=True),
    Output("pipeline-region", "children", allow_duplicate=True),
    Output("pip-progress", "disabled", allow_duplicate=True),
    Input("cancel-agents", "n_clicks"),
    State("store-pipeline", "data"),
    prevent_initial_call=True,
)
def cancel_agents(n_clicks, states):
    """Request cancellation of the run in flight."""
    global _ACTIVE_RUN

    try:
        if not n_clicks:
            return (no_update,) * 3

        run = _ACTIVE_RUN
        if run is None:
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
            )

        run.cancel()
        _ledger_add("run", "cancelled", 0, "cancel requested by the operator")

        snapshot = run.pipeline.to_dict() if run.pipeline is not None else states
        return (
            snapshot,
            _render_pipeline_region(snapshot, None),
            False,
        )
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("cancel_agents failed: %s" % traceback.format_exc().splitlines()[-1])
        return (
            no_update,
            _render_pipeline_region(states, None),
            no_update,
        )


@app.callback(
    Output("store-pipeline", "data", allow_duplicate=True),
    Output("pipeline-region", "children", allow_duplicate=True),
    Output("pip-progress", "disabled", allow_duplicate=True),
    Output("review-alert", "children", allow_duplicate=True),
    Input({"type": "agent-rerun", "persona": dash_ALL}, "n_clicks"),
    State("store-document", "data"),
    State("store-pipeline", "data"),
    State("store-provider", "data"),
    prevent_initial_call=True,
)
def rerun_agent(clicks, document, states, provider):
    """Re-run a single agent persona after it finished, failed, or was cancelled."""
    global _ACTIVE_RUN

    try:
        if not clicks or not any(clicks):
            return (no_update,) * 4

        persona = None
        try:
            from dash import ctx

            triggered = ctx.triggered_id
            if isinstance(triggered, dict):
                persona = triggered.get("persona")
        except Exception:  # noqa: BLE001 - fall back to the first rerun button
            persona = None
        if persona not in PERSONA_STAGE:
            persona = "citation"
        stage_name = PERSONA_STAGE[persona]

        text = _text((document or {}).get("text"))
        if not text.strip():
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                _alert(
                    "No manuscript loaded",
                    "A re-run needs manuscript text to review.",
                    "Upload a manuscript first.",
                ),
            )

        if _ACTIVE_RUN is not None and _ACTIVE_RUN.is_running():
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                _alert(
                    "A run is already in flight",
                    "Only one agent run may execute at a time.",
                    "Cancel the current run, then re-run the single agent.",
                ),
            )

        provider_key = (provider or {}).get("provider", "local")
        config = _provider_config(provider_key)
        client, error = _build_llm_client(provider_key)
        if client is None:
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                _alert(
                    "Engine unavailable",
                    error or "No LLM client could be constructed.",
                    "Check the engine configuration in the Engine panel, then try again.",
                ),
            )

        state = _pipeline_from_states(states)
        if state is None:
            return (no_update,) * 4

        try:
            from runner import ReviewRun
        except ImportError as exc:
            return (
                no_update,
                _render_pipeline_region(states, None),
                no_update,
                _alert(
                    "Runner unavailable",
                    "The background review runner is not importable: %s" % exc,
                    "Confirm src/runner.py is present, then try again.",
                ),
            )

        stage_name = PERSONA_STAGE[persona]
        # A re-run starts from a clean stage so the timestamps and count
        # reflect this execution rather than the previous one.
        state.set_status(stage_name, "pending")
        state.set_count(stage_name, 0)

        run = ReviewRun(
            client,
            selected=[stage_name],
            pipeline=state,
        )
        run.start(text)
        _ACTIVE_RUN = run

        _ledger_add(
            stage_name,
            "running",
            0,
            "re-run requested on %s" % config["label"],
        )

        snapshot = state.to_dict()
        return (
            snapshot,
            _render_pipeline_region(snapshot, None),
            False,
            [],
        )
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("rerun_agent failed: %s" % traceback.format_exc().splitlines()[-1])
        return (
            no_update,
            _render_pipeline_region(states, None),
            no_update,
            _alert(
                "Re-run failed to start",
                "The single agent could not be restarted: %s" % exc,
                "Try again, or check the engine configuration in the Engine panel.",
            ),
        )


@app.callback(
    Output("store-pipeline", "data", allow_duplicate=True),
    Output("pipeline-region", "children", allow_duplicate=True),
    Output("pip-progress", "disabled", allow_duplicate=True),
    Output("store-findings", "data", allow_duplicate=True),
    Output("findings-list", "children", allow_duplicate=True),
    Output("review-count", "children", allow_duplicate=True),
    Output("ledger-list", "children", allow_duplicate=True),
    Input("pip-progress", "n_intervals"),
    State("store-document", "data"),
    State("store-pipeline", "data"),
    State("store-findings", "data"),
    State("store-provider", "data"),
    prevent_initial_call=True,
)
def pip_progress_tick(n_intervals, document, states, findings, provider):
    """Poll the live run and republish the strip, the board, and the ledger.

    This is the only place the browser learns about background progress. It
    never raises: with no document, no run, or no runner it simply leaves
    the page as it is.
    """
    global _ACTIVE_RUN

    try:
        run = _ACTIVE_RUN
        if run is None:
            return (no_update,) * 7

        provider_key = (provider or {}).get("provider", "local")
        config = _provider_config(provider_key)

        snapshot = states
        if run.pipeline is not None:
            snapshot = run.pipeline.to_dict()

        merged = _merge_findings(findings or [], _agent_findings(run, config["label"]))
        _ledger_from_pipeline(snapshot)

        running = False
        try:
            running = bool(run.is_running())
        except Exception:  # noqa: BLE001 - treat an unreadable runner as stopped
            running = False

        if running:
            return (
                snapshot,
                _render_pipeline_region(snapshot, None),
                False,
                merged,
                _findings_view(merged, "all"),
                _findings_count_label(merged),
                _render_ledger(),
            )

        # The run settled: stop the clock and close the ledger.
        progress = run.progress_snapshot()
        message = _text(progress.get("message")) or "finished"
        _ledger_add(
            "run",
            "done" if message == "finished" else message,
            run.findings_count(),
            "run settled: %s" % message,
        )
        _ACTIVE_RUN = None

        return (
            snapshot,
            _render_pipeline_region(snapshot, None),
            True,
            merged,
            _findings_view(merged, "all"),
            _findings_count_label(merged),
            _render_ledger(),
        )
    except Exception as exc:  # noqa: BLE001 - a polling tick must never raise
        _log("pip_progress_tick failed: %s" % traceback.format_exc().splitlines()[-1])
        return (no_update,) * 7


@app.callback(
    Output("store-selected-stage", "data"),
    Output("store-inspector-stage", "data"),
    Output("stage-detail", "children"),
    Input({"type": "stage-focus", "stage": dash_ALL}, "n_clicks"),
    State("store-pipeline", "data"),
    prevent_initial_call=True,
)
def pip_stage_focus(clicks, states):
    """Open the detail panel for the stage card the operator clicked.

    Writes both the selected-stage store (drives the accordion highlight) and
    the inspector-stage store (the save callback reads it to know which
    stage's prompt config it is persisting).
    """
    try:
        if not clicks or not any(clicks):
            return (no_update, no_update, no_update)

        name = None
        try:
            from dash import ctx

            triggered = ctx.triggered_id
            if isinstance(triggered, dict):
                name = triggered.get("stage")
        except Exception:  # noqa: BLE001 - fall back to the first stage
            name = None
        if name not in PIPELINE_STAGE_ORDER:
            name = PIPELINE_STAGE_ORDER[0]

        rows = _stage_rows(states)
        row = rows[PIPELINE_STAGE_ORDER.index(name)]
        return name, name, _stage_detail_body(row, states)
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("pip_stage_focus failed: %s" % traceback.format_exc().splitlines()[-1])
        return (no_update, no_update, no_update)


@app.callback(
    Output("stage-detail", "children", allow_duplicate=True),
    Output("inspector-status", "children"),
    Input({"type": "ref-upload", "doc": dash_ALL}, "contents"),
    State({"type": "ref-upload", "doc": dash_ALL}, "filename"),
    State("store-inspector-stage", "data"),
    State("store-pipeline", "data"),
    prevent_initial_call=True,
)
def ref_upload_save(contents_list, filename_list, stage, states):
    """Store an uploaded reference manual and refresh the open editor.

    The editor is re-rendered so the document flips to [Loaded] immediately.
    Unsaved prompt edits in the open editor are reset by that refresh - the
    status line says so when it happens.
    """
    try:
        doc_key = None
        contents = None
        filename = None
        try:
            from dash import ctx

            triggered = ctx.triggered_id
            doc_key = triggered.get("doc") if isinstance(triggered, dict) else None

            def _entries(role):
                try:
                    groups = ctx.inputs_list if role == "inputs" else ctx.states_list
                    return (groups or [])[0] or []
                except Exception:  # noqa: BLE001 - context shape may vary
                    return []

            for entry in _entries("inputs"):
                eid = entry.get("id")
                if isinstance(eid, dict) and eid.get("doc") == doc_key:
                    contents = entry.get("value")
                    break
            for entry in _entries("states"):
                eid = entry.get("id")
                if isinstance(eid, dict) and eid.get("doc") == doc_key:
                    filename = entry.get("value")
                    break
        except Exception:  # noqa: BLE001 - fall back to positional lists
            doc_key = None

        if not doc_key:
            return no_update, no_update
        if not contents:
            # dcc.Upload only reports contents after a real file selection;
            # an empty firing here is a spurious re-render, stay silent so we
            # never stomp a fresher status message.
            return no_update, no_update
        if _run_is_blocking_save(states):
            return (
                no_update,
                "Blocked: a run is in progress. Upload the reference after "
                "the run finishes or is cancelled.",
            )

        filename = filename_list[0] if not filename and filename_list else filename
        ok, message = _save_reference_document(doc_key, filename, contents)

        name = stage if stage in PIPELINE_STAGE_ORDER else PIPELINE_STAGE_ORDER[0]
        rows = _stage_rows(states)
        row = rows[PIPELINE_STAGE_ORDER.index(name)]
        body = _stage_detail_body(row, states)
        if not ok:
            return body, message
        return body, (
            "%s The editor refreshed so the document shows [Loaded]. "
            "Note: unsaved prompt edits were reset by the refresh." % message
        )
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("ref_upload_save failed: %s" % traceback.format_exc().splitlines()[-1])
        return no_update, "The upload could not be completed: %s" % exc


@app.callback(
    Output("stage-detail", "children", allow_duplicate=True),
    Output("inspector-status", "children"),
    Input({"type": "history-restore", "stage": dash_ALL, "version": dash_ALL},
          "n_clicks"),
    State("store-inspector-stage", "data"),
    State("store-pipeline", "data"),
    prevent_initial_call=True,
)
def history_restore(n_clicks_list, stage, states):
    """Roll a node's prompt config back to an archived version.

    The restore lands as a NEW version (the replaced current config is
    archived first), so a rollback is itself undoable. The editor body is
    re-rendered so the textareas show the restored text.
    """
    try:
        target_stage = None
        version = None
        try:
            from dash import ctx

            triggered = ctx.triggered_id
            if (isinstance(triggered, dict)
                    and triggered.get("type") == "history-restore"):
                target_stage = triggered.get("stage")
                version = triggered.get("version")
        except Exception:  # noqa: BLE001 - no context, no target
            target_stage = None

        skey = target_stage if target_stage in PIPELINE_STAGE_ORDER else None
        if skey is None:
            # Spurious re-render firing (no real button): stay silent.
            return no_update, no_update

        if _run_is_blocking_save(states):
            return (
                no_update,
                "Blocked: a run is in progress. Roll back after the run "
                "finishes or is cancelled.",
            )

        import prompt_history

        ok, message = prompt_history.restore(skey, version)
        rows = _stage_rows(states)
        row = rows[PIPELINE_STAGE_ORDER.index(skey)]
        body = _stage_detail_body(row, states)
        if not ok:
            return body, message
        return body, message + " Unsaved edits were reset by the refresh."
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("history_restore failed: %s" % traceback.format_exc().splitlines()[-1])
        return no_update, "The roll back could not be completed: %s" % exc


# --------------------------------------------------------------------------
# Prompt editor callbacks: save the edited per-node prompt configuration.
# --------------------------------------------------------------------------


def _run_is_blocking_save(states):
    """True when a save must be blocked by an in-flight run.

    Mirrors the existing Cancel callback gate (_ACTIVE_RUN is not None) and
    also blocks while any stage reports a running status.
    """
    if _ACTIVE_RUN is not None:
        return True
    for row in _stage_rows(states):
        if row["status"] == "running":
            return True
    return False


@app.callback(
    Output("inspector-status", "children"),
    Output("store-prompts-cache", "data"),
    Input("inspector-save", "n_clicks"),
    State("inspector-model", "value"),
    State("inspector-temp", "value"),
    State("inspector-max-tokens", "value"),
    State("inspector-outlet", "value"),
    State({"type": "inspector-prompt", "key": dash_ALL}, "value"),
    State("store-inspector-stage", "data"),
    State("store-pipeline", "data"),
    prevent_initial_call=True,
)
def canvas_inspector_save(n_clicks, model, temp, max_tokens, outlet, prompt_values, stage, states):
    """Validate and atomically write the edited prompt config to disk."""
    try:
        if not n_clicks:
            return no_update, no_update

        if _run_is_blocking_save(states):
            return (
                "Blocked: a run is in progress. Prompts are locked until the "
                "run finishes or is cancelled.",
                no_update,
            )

        key = stage
        if stage not in PIPELINE_STAGE_ORDER:
            return "No prompt configuration for this stage.", no_update

        try:
            temp_value = float(temp)
        except (TypeError, ValueError):
            return "Invalid temperature: must be a number from 0 to 2.", no_update
        if not (0 <= temp_value <= 2):
            return "Invalid temperature: must be from 0 to 2.", no_update

        try:
            tokens_value = int(max_tokens)
        except (TypeError, ValueError):
            return "Invalid max tokens: must be an integer from 1 to 32000.", no_update
        if not (1 <= tokens_value <= 32000):
            return "Invalid max tokens: must be from 1 to 32000.", no_update

        path = os.path.join(BASE_DIR, "configs", "prompts.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            return "Could not read configs/prompts.json: %s" % exc, no_update

        cfg = data.get("stages", {}).get(key)
        if not isinstance(cfg, dict):
            return "No prompt configuration for this stage.", no_update

        # Archive the config being replaced so it can be rolled back.
        try:
            import prompt_history

            prompt_history.append_history(key, cfg)
        except Exception as exc:  # noqa: BLE001 - history must never block saves
            _log("prompt history archive failed: %s" % exc)

        # Map each delivered prompt value to its key by the pattern-matching
        # id, never by position. Dash delivers pattern State values in render
        # order and also exposes ctx.states_list as {id, value} pairs; we use
        # the ids so a reorder of the textareas can never write a prompt to
        # the wrong key.
        prompt_keys = sorted((cfg.get("prompts") or {}).keys())
        prompt_map = {}
        try:
            from dash import ctx

            for sid, sval in (ctx.states_list or []):
                if (isinstance(sid, dict) and sid.get("type") == "inspector-prompt"
                        and sid.get("key") in prompt_keys):
                    prompt_map[sid["key"]] = sval
        except Exception:  # noqa: BLE001 - fall back to positional order
            prompt_map = {
                pk: pv for pk, pv in zip(prompt_keys, prompt_values or [])
            }
        missing = [pk for pk in prompt_keys if pk not in prompt_map]
        if missing:
            return "Prompt fields did not load correctly (missing: %s)." % ", ".join(missing), no_update
        for pk, pv in prompt_map.items():
            if not _text(pv).strip():
                return "Prompt fields must not be empty.", no_update

        # Persist the edited prompts, model params, outlet, and (Part 1) the
        # attached reference-document selection from the checklist.
        outlet_value = _text(outlet)
        valid_outlets = {""}
        try:
            import outlets as outlets_mod

            valid_outlets |= {
                o.get("key") for o in (outlets_mod.load_outlets().get("outlets") or [])
            }
        except Exception:  # noqa: BLE001 - registry absent: default only
            pass
        if outlet_value not in valid_outlets:
            return "Invalid outlet: %s. Save again after picking one from the list." % (
                outlet_value or "(empty)"), no_update

        ref_keys = _reference_keys()
        ref_selected = []
        try:
            from dash import ctx

            for sid, sval in (ctx.states_list or []):
                if (isinstance(sid, dict) and sid.get("type") == "ref-attach"
                        and sid.get("stage") == key):
                    ref_selected = list(sval or [])
                    break
        except Exception:  # noqa: BLE001 - keep current attachments on failure
            ref_selected = cfg.get("references") or []

        cfg["model"] = _text(model)
        cfg["temperature"] = temp_value
        cfg["max_tokens"] = tokens_value
        cfg["outlet"] = outlet_value
        cfg["prompts"] = {pk: _text(prompt_map[pk]) for pk in prompt_keys}
        cfg["references"] = [k for k in ref_keys if k in ref_selected]
        cfg["version"] = int(cfg.get("version") or 0) + 1
        cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
        data["stages"][key] = cfg

        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=2)
        os.replace(tmp_path, path)

        try:
            from prompts import load_store

            refreshed, _ = load_store()
        except Exception:  # noqa: BLE001 - fall back to the in-memory dict
            refreshed = data
        return "Saved. Version %d." % cfg["version"], refreshed
    except Exception as exc:  # noqa: BLE001 - never raise out of a callback
        _log("canvas_inspector_save failed: %s" % exc)
        return "Save failed: %s" % exc, no_update


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

if __name__ == "__main__":
    # Bind to localhost by default. Set ASK_DASH_HOST=0.0.0.0 to share the
    # review agent with other devices on the LAN (no auth in this prototype).
    app.run(host=os.getenv("ASK_DASH_HOST", "127.0.0.1"), port=8501, debug=False)
