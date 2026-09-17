"""Pubs Review Agent pipeline engine (Goal 1).

Adopts the proven "Pubs Review Agent v3" AskSage workflow (replicated in
DAPAM_OCR/pubs_review) into AskSageProofAgent_Local. It runs the 7 sequential
stages against the app's two-outlet LLM client:

    S1 Extract & Parse        -> manuscript_details
    S2 Cross-Section Analysis -> cross_section_results
    S3 Citations + APA Review -> citations_final
    S4 SME + Statistics       -> sme_final
    S5 CopyEdit + Bias        -> copyedit_final
    S6 Dedup & Consolidate    -> consolidated_review
    S7 Generate Final Report  -> final_report

Prompts come from configs/prompts.json (via src/prompts.py), which the boss
can inspect and edit. Compliance labels are produced by the LLM's
"OVERALL ASSESSMENT:" line and extracted with regex (no separate LLM call).
Findings are normalized into the shared schema (agent/domain, severity,
location, original_text, issue, correction, source, provenance).

ASCII/English only. This module performs no I/O except through the LLM client
and the prompt store; it never starts threads.
"""

import os
import re
import sys

import prompts as prompt_store

try:  # optional module; the pipeline still runs without it
    import references as ref_store
except Exception:  # noqa: BLE001 - never hard-fail on a missing optional module
    ref_store = None

# Valid severities and the proven 3 review domains.
SEVERITIES = ("CRITICAL", "MAJOR", "MODERATE", "MINOR")
COMPLIANCE_LABELS = ("COMPLIANT", "PARTIALLY_COMPLIANT", "NON_COMPLIANT")

# stage key -> (display name, review domain)
STAGE_META = {
    "s1_extract": ("Extract & Parse Manuscript", None),
    "s2_cross_section": ("Cross-Section Analysis", None),
    "s3_citations": ("Citations + APA Review", "citations"),
    "s4_sme": ("SME + Statistics Review", "sme"),
    "s5_copyedit": ("CopyEdit + Bias + Originality", "copyedit"),
    "s6_dedup": ("Dedup & Consolidate", None),
    "s7_report": ("Generate Final Report", None),
}

STAGE_ORDER = ["s1_extract", "s2_cross_section", "s3_citations",
               "s4_sme", "s5_copyedit", "s6_dedup", "s7_report"]


def compliance_pattern():
    return re.compile(r"OVERALL\s+ASSESSMENT:\s*\[?\s*"
                      r"(NON[-\s_]?COMPLIANT|PARTIALLY[-\s_]?COMPLIANT|COMPLIANT)",
                      re.IGNORECASE)


_PIPE = str.maketrans({"-": "", " ": "", "_": ""})


def _norm(label):
    return (label or "").upper().translate(_PIPE)


def extract_compliance_label(text):
    """Extract the compliance label from an LLM analysis response.

    Accepts COMPLIANT, PARTIALLY COMPLIANT, and NON COMPLIANT in a range of
    spellings (hyphens, spaces, underscores, leading/trailing text). The
    OVERALL ASSESSMENT line is matched first; otherwise a normalized substring
    scan. Non-compliant is tested before compliant so the substring match
    cannot return COMPLIANT for "NON COMPLIANT". Defaults to
    PARTIALLY_COMPLIANT (a safe middle ground) when nothing is found.
    """
    m = compliance_pattern().search(text or "")
    if m:
        raw = _norm(m.group(1))
        if "NONCOMPLIANT" in raw:
            return "NON_COMPLIANT"
        if "PARTIALLYCOMPLIANT" in raw:
            return "PARTIALLY_COMPLIANT"
        return "COMPLIANT"
    norm = _norm(text)
    if "NONCOMPLIANT" in norm:
        return "NON_COMPLIANT"
    if "PARTIALLYCOMPLIANT" in norm or "PARTIALLY COMPLIANT" in (text or "").upper():
        return "PARTIALLY_COMPLIANT"
    if "COMPLIANT" in norm:
        return "COMPLIANT"
    return "PARTIALLY_COMPLIANT"


def normalize_severity(sev):
    """Coerce any severity string to one of CRITICAL/MAJOR/MODERATE/MINOR."""
    if not sev:
        return "MINOR"
    s = str(sev).strip().upper()
    for cand in SEVERITIES:
        if cand == s:
            return cand
    if "CRITICAL" in s:
        return "CRITICAL"
    if "MAJOR" in s:
        return "MAJOR"
    if "MODERATE" in s or "MEDIUM" in s:
        return "MODERATE"
    return "MINOR"


# Mapping from the proven review domains to the existing app agent labels.
DOMAIN_TO_AGENT = {
    "citations": "citation",
    "apa": "apa",
    "sme": "sme",
    "copyedit": "apa",
    "statistics": "sme",
    "bias": "apa",
    "originality": "apa",
    "compliance": "apa",
    "structure": "citation",
    "other": "apa",
}

# CRITICAL/MAJOR -> error, MODERATE -> warning, MINOR -> info (existing scheme).
SEV_TO_APP = {"CRITICAL": "error", "MAJOR": "error",
              "MODERATE": "warning", "MINOR": "info"}


def to_app_finding(finding):
    """Convert a proven-pipeline finding dict to the shared app schema.

    The app's findings board expects FINDING_KEYS:
    agent, severity, location, original_text, issue, suggested_fix, source.
    This adapter maps domain->agent and CRITICAL/MAJOR/MODERATE/MINOR->
    error/warning/info so both engines render through the same UI.
    """
    domain = finding.get("domain") or "other"
    agent = DOMAIN_TO_AGENT.get(str(domain).lower(), "apa")
    sev = normalize_severity(finding.get("severity"))
    return {
        "agent": agent,
        "severity": SEV_TO_APP.get(sev, "info"),
        "location": finding.get("location") or "Document",
        "original_text": finding.get("original_text") or finding.get("issue") or "",
        "issue": finding.get("issue") or "",
        "suggested_fix": finding.get("correction") or finding.get("suggested_fix") or "",
        "source": finding.get("source") or "ARI/APA publication standards",
    }


def findings_to_app(findings):
    """Convert a list of proven findings to the shared app schema list."""
    return [to_app_finding(f) for f in findings]


class ProviderAdapter:
    """Adapts our two-outlet LLMClient to the proven provider.complete() shape.

    Maps a prompt to a single user chat message and returns a normalized
    response. This is the single integration point between the proven stage
    logic and the app's LLM client (Maple local + custom fallback).
    """

    def __init__(self, llm_client, model_override=None):
        self.client = llm_client
        self.model_override = model_override
        # Best-effort model name for reporting.
        self.model = getattr(llm_client, "model", "local")

    def complete(self, prompt, temperature=0.2, max_tokens=4096):
        text = self.client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            model_override=self.model_override,
        )
        return text


def _fill(template, context):
    """Replace {{...}} placeholders using a dotted-lookup against context."""
    def repl(m):
        path = m.group(1).strip()
        return _lookup(context, path, m.group(0))
    return re.sub(r"\{\{\s*((?:\w+\.)*\w+)\s*\}\}", repl, template)


def _lookup(context, path, default):
    parts = path.split(".")
    # input.target_journal -> context["target_journal"] (drop "input" prefix)
    if parts and parts[0] == "input":
        parts = parts[1:]
    node = context
    for p in parts:
        if isinstance(node, dict) and p in node:
            node = node[p]
        else:
            return default
    return str(node) if node is not None else default


def parse_llm_findings(text, domain=None):
    """Best-effort parse of an analysis block into finding dicts.

    Handles the proven markdown table format:
        | Page | Original Text | Issue | Correction | APA/ARI Source | Severity |
    Falls back to extracting the OVERALL ASSESSMENT as a finding when no
    table rows are found. Never raises; returns a list of dicts.
    """
    findings = []
    if not text:
        return findings
    lines = [ln.strip() for ln in text.splitlines()]
    for ln in lines:
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        cells = [c for c in cells if c != ""]
        if len(cells) < 4:
            continue
        # Skip header separators like |---|---|
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        # Skip the table header row (ends in a "Severity" label, not a value).
        last = cells[-1].upper()
        if last not in SEVERITIES and last in ("SEVERITY", "PAGE", "SOURCE", "ORIGINAL TEXT", "ISSUE", "CORRECTION"):
            continue
        severity = normalize_severity(cells[-1] if cells else "")
        location = cells[0] if cells else "Document"
        original = cells[1] if len(cells) > 1 else ""
        issue = cells[2] if len(cells) > 2 else ""
        correction = cells[3] if len(cells) > 3 else ""
        source = cells[4] if len(cells) > 4 else ""
        findings.append({
            "domain": domain,
            "severity": severity,
            "location": location,
            "original_text": original,
            "issue": issue,
            "correction": correction,
            "source": source,
        })
    return findings


class PubPipeline:
    """Sequential 7-stage publicaions review pipeline.

    Usage:
        from llm_client import LLMClient
        from pub_pipeline import PubPipeline, ProviderAdapter
        pipe = PubPipeline(ProviderAdapter(LLMClient('local')))
        result = pipe.run(manuscript_text=..., target_journal="Military Psychology")
    """

    def __init__(self, adapter, store=None, client_factory=None):
        self.adapter = adapter
        self.client_factory = client_factory
        self.store, _warn = (
            (store, "") if store is not None else prompt_store.load_store())

    # -- prompt composition ------------------------------------------------

    def _stage_cfg(self, stage):
        """Return the stage's config dict from the prompt store (or {})."""
        cfg = prompt_store.find_stage_config(self.store, stage)
        return cfg if isinstance(cfg, dict) else {}

    def _adapter_for(self, stage):
        """Return the adapter for one stage: its pinned outlet, or the default.

        A stage whose saved config names an outlet (configs/outlets.json)
        gets its own client through client_factory. Unknown keys, missing
        factory, or any factory failure fall back to the run-wide adapter so
        one bad outlet setting can never stall the whole review.
        """
        outlet = str((self._stage_cfg(stage) or {}).get("outlet") or "").strip()
        if not outlet or self.client_factory is None:
            return self.adapter
        try:
            client = self.client_factory(outlet)
        except Exception:
            client = None
        if client is None:
            return self.adapter
        return ProviderAdapter(client)

    def _stage_references_block(self, stage):
        """Return the injected reference block for the stage's attachments."""
        if ref_store is None:
            return ""
        cfg = self._stage_cfg(stage)
        keys = cfg.get("references") or []
        return ref_store.attachments_for(keys) if keys else ""

    def _compose(self, stage, template, ctx):
        """Fill a prompt template, prepending the stage's reference docs."""
        filled = _fill(template or "", ctx)
        refs = self._stage_references_block(stage)
        if refs:
            filled = refs + "\n\n" + filled
        return filled

    # -- stage runners -----------------------------------------------------

    def run_stage1(self, ctx):
        cfg = self._stage_cfg("s1_extract")
        tmpl = prompt_store.get_prompt(self.store, "s1_extract", "EXTRACT_PROMPT")
        ctx["s1_result"] = self._adapter_for("s1_extract").complete(
            self._compose("s1_extract", tmpl, ctx),
            temperature=cfg.get("temperature", 0.1),
            max_tokens=cfg.get("max_tokens", 2000))
        ctx["manuscript_details"] = ctx["s1_result"]

    def run_stage2(self, ctx):
        cfg = self._stage_cfg("s2_cross_section")
        tmpl = prompt_store.get_prompt(self.store, "s2_cross_section", "CROSS_SECTION_PROMPT")
        ctx["s2_result"] = self._adapter_for("s2_cross_section").complete(
            self._compose("s2_cross_section", tmpl, ctx),
            temperature=cfg.get("temperature", 0.1),
            max_tokens=cfg.get("max_tokens", 1024))
        ctx["cross_section_results"] = ctx["s2_result"]

    def _run_review_block(self, ctx, stage, analysis_key, prefix):
        """Run one review block: analysis -> label -> branch -> final."""
        cfg = prompt_store.find_stage_config(self.store, stage)
        prompts = (cfg or {}).get("prompts", {})
        stage_max = (cfg or {}).get("max_tokens", 1024)
        stage_temp = (cfg or {}).get("temperature", 0.2)
        adapter = self._adapter_for(stage)
        analysis_tmpl = prompts.get(prefix + "_ANALYSIS_PROMPT")
        analysis = adapter.complete(
            self._compose(stage, analysis_tmpl, ctx),
            temperature=stage_temp,
            max_tokens=stage_max)
        ctx[analysis_key] = analysis
        ctx[analysis_key + "_findings"] = parse_llm_findings(analysis, prefix.lower().split("_")[0])

        label = extract_compliance_label(analysis)
        ctx[analysis_key + "_label"] = label

        branch_key = {"COMPLIANT": prefix + "_COMPLIANT_PROMPT",
                      "PARTIALLY_COMPLIANT": prefix + "_PARTIALLY_PROMPT",
                      "NON_COMPLIANT": prefix + "_NON_COMPLIANT_PROMPT"}[label]
        branch = adapter.complete(
            self._compose(stage, prompts.get(branch_key, ""), ctx),
            temperature=min(stage_temp + 0.05, 0.5), max_tokens=stage_max)
        ctx[prefix.lower().replace("_", "") + "_branch"] = branch

        # Final formatter, domain-dependent table.
        final_tmpl = prompts.get(prefix + "_FINAL_PROMPT")
        final = adapter.complete(
            self._compose(stage, final_tmpl, ctx),
            temperature=stage_temp, max_tokens=stage_max)
        ctx[prefix.lower().replace("_", "") + "_final"] = final

    def run_stage3(self, ctx):
        self._run_review_block(ctx, "s3_citations", "citations_apa_analysis", "CITATIONS")

    def run_stage4(self, ctx):
        self._run_review_block(ctx, "s4_sme", "sme_analysis", "SME")

    def run_stage5(self, ctx):
        self._run_review_block(ctx, "s5_copyedit", "copyedit_analysis", "COPYEDIT")

    def run_stage6(self, ctx):
        cfg = self._stage_cfg("s6_dedup")
        tmpl = prompt_store.get_prompt(self.store, "s6_dedup", "DEDUP_PROMPT")
        ctx["s6_result"] = self._adapter_for("s6_dedup").complete(
            self._compose("s6_dedup", tmpl, ctx),
            temperature=cfg.get("temperature", 0.0),
            max_tokens=cfg.get("max_tokens", 1024))
        ctx["consolidated_review"] = ctx["s6_result"]

    def run_stage7(self, ctx):
        cfg = self._stage_cfg("s7_report")
        tmpl = prompt_store.get_prompt(self.store, "s7_report", "REPORT_PROMPT")
        ctx["s7_result"] = self._adapter_for("s7_report").complete(
            self._compose("s7_report", tmpl, ctx),
            temperature=cfg.get("temperature", 0.3),
            max_tokens=cfg.get("max_tokens", 1500))
        ctx["final_report"] = ctx["s7_result"]

    # -- orchestration -----------------------------------------------------

    STAGE_RUNNERS = {
        "s1_extract": "run_stage1", "s2_cross_section": "run_stage2",
        "s3_citations": "run_stage3", "s4_sme": "run_stage4",
        "s5_copyedit": "run_stage5", "s6_dedup": "run_stage6",
        "s7_report": "run_stage7",
    }

    def run(self, manuscript_text="", manuscript_path="", ari_manual_text="",
            ar_rag_text="", target_journal="Military Psychology",
            apa_edition="7th", output_mode="both", distribution_statement=""):
        ctx = {
            "manuscript_text": manuscript_text,
            "manuscript_path": manuscript_path,
            "ari_manual_text": ari_manual_text,
            "ar_rag_text": ar_rag_text,
            "target_journal": target_journal,
            "apa_edition": apa_edition,
            "output_mode": output_mode,
            "distribution_statement": distribution_statement,
        }
        results = {}
        for stage in STAGE_ORDER:
            runner = getattr(self, self.STAGE_RUNNERS[stage])
            runner(ctx)
            rkey = self._result_key(stage)
            results[stage] = ctx.get(rkey)
            ctx[stage] = ctx.get(rkey)  # also store under the stage key
        # Assemble findings from all review blocks + dedup.
        findings = []
        for key in ("citations_apa_analysis", "sme_analysis", "copyedit_analysis"):
            findings.extend(ctx.get(key + "_findings", []))
        ctx["findings"] = findings
        ctx["per_stage_compliance"] = {
            "s3_citations": ctx.get("citations_apa_analysis_label"),
            "s4_sme": ctx.get("sme_analysis_label"),
            "s5_copyedit": ctx.get("copyedit_analysis_label"),
        }
        return ctx

    def _result_key(self, stage):
        return {
            "s1_extract": "s1_result", "s2_cross_section": "s2_result",
            "s3_citations": "citations_final", "s4_sme": "sme_final",
            "s5_copyedit": "copyedit_final", "s6_dedup": "s6_result",
            "s7_report": "s7_result",
        }[stage]


def build_pipeline(llm_client, store=None, client_factory=None):
    """Convenience factory: wrap an LLMClient and build the pipeline.

    client_factory(outlet_key) -> client lets individual stages run on their
    own named outlet (configs/outlets.json); None keeps every stage on the
    run-wide client.
    """
    return PubPipeline(ProviderAdapter(llm_client), store=store,
                       client_factory=client_factory)


def summary_counts(findings):
    """Count findings into the shared summary shape (error/warning/info/total)."""
    summary = {"error": 0, "warning": 0, "info": 0, "total": 0}
    for f in findings:
        sev = f.get("severity", "info")
        if sev in summary:
            summary[sev] += 1
        summary["total"] += 1
    return summary


def _dedupe_app_findings(findings):
    """Drop duplicate app-schema findings on (agent, location, issue)."""
    seen = set()
    out = []
    for f in findings:
        key = (f.get("agent"), f.get("location"), f.get("issue"))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def run_review(
    text,
    agents=("citation", "apa", "sme"),
    reference_text=None,
    llm_client=None,
    page_map=None,
    progress=None,
):
    """Run the combined review: deterministic rules + the proven 7-stage pass.

    This matches the review_agents.run_review() signature so the dashboard can
    swap engines by pointing REVIEW_ENGINE at this module. Returns the shared
    dict shape: findings, summary, agents_run, skipped, notes.

    The deterministic RuleEngine always runs (offline ground truth). When
    llm_client is provided, the proven S1-S7 pipeline runs on top and its
    findings are normalized into the shared app schema and appended.
    """
    notes = []
    agents_run = []
    skipped = []

    if progress:
        progress("s2_cross_section", 0.0)

    # Layer 1 - deterministic rules (ground truth, offline).
    from review_agents import RuleEngine
    rule_findings = RuleEngine(page_map=page_map).run(text or "", reference_text or "")
    findings = list(rule_findings)

    if llm_client is not None:
        if progress:
            progress("llm:seven_stage", 0.3)
        try:
            adapter = ProviderAdapter(llm_client)
            pipe = PubPipeline(adapter, store=None)
            ctx = pipe.run(
                manuscript_text=text or "",
                reference_text=reference_text or "",
                target_journal=_TARGET_JOURNAL,
            )
            proven = ctx.get("findings", [])
            prior = len(findings)
            findings.extend(findings_to_app(proven))
            notes.append("Proven 7-stage pass produced %d finding(s)." % len(proven))
            agents_run.extend(("citation", "apa", "sme"))
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            notes.append("Proven 7-stage pass failed: %s" % exc)
    else:
        for persona in agents:
            skipped.append(
                "{}: 7-stage pass skipped (no llm_client provided); "
                "deterministic rules only.".format(persona)
            )

    findings = _dedupe_app_findings(findings)
    if progress:
        progress("done", 1.0)
    return {
        "findings": findings,
        "summary": summary_counts(findings),
        "agents_run": agents_run or list(agents),
        "skipped": skipped,
        "notes": notes,
    }


_TARGET_JOURNAL = "Military Psychology"

