# G1-R2 Design: Adopting the 7-Stage Pubs Review Pipeline into AskSageProofAgent_Local

Status: PLANNED (Goal 1)
Audience: G1 execution agent (DeepSeek-Flash) and human reviewers.
Companion doc: G1-R3-runbook.md (ordered build steps).

All text in this document is English and ASCII only.

## 0. Scope and Non-Goals

Goal 1 ports the proven Pubs Review Agent v3 pipeline (7 stages, 22 verbatim
prompts, compliance regex, unified branch prompt, ~10 LLM calls per manuscript)
into C:\Users\haiji\Documents\AskSageProofAgent_Local\, wired to the existing
two-outlet LLM client (src\llm_client.py: provider "local" = Maple, "custom").

Non-goals for G1: UI redesign, Docker changes, new providers, multi-document
batching, changing the existing "custom" outlet contract.

## 1. Architecture: How to Bridge DAPAM_OCR\pubs_review

### 1.1 Option A: Import prompt templates into configs\prompts.json (RECOMMENDED)

Copy the 22 prompt template strings (extracted byte-identical from
DAPAM_OCR\asksage_workflow_v3_clean.json node config.prompt_template values,
cross-checked against DAPAM_OCR\pubs_review\prompts\*.py) into a single JSON
store at AskSageProofAgent_Local\configs\prompts.json. Re-implement the thin
stage logic (7 stages) natively in AskSageProofAgent_Local\src\, calling
LLMClient.chat_completion. Port the compliance regex from
pubs_review\utils\compliance.py into AskSageProofAgent_Local\src\compliance.py.

Pros:
- Single editable prompt store; end users can tweak prompts without touching
  Python; matches the app's existing config-driven style.
- No cross-project import: AskSageProofAgent_Local becomes self-contained;
  DAPAM_OCR can evolve or disappear without breaking it.
- The prompt text is the proven asset; the surrounding pubs_review plumbing
  (providers ABC, foundry/ollama providers) is redundant because
  src\llm_client.py already fills that role.
- Avoids duplicated provider stacks and divergent dataclasses.

Cons:
- One-time extraction risk: prompts must be copied byte-identical (mitigated
  by a verification test that diffs JSON values against the source JSON).
- Future upstream fixes in pubs_review must be re-imported manually.

### 1.2 Option B: Copy pubs_review as a vendored module

Copy the whole pubs_review package under AskSageProofAgent_Local\vendor\ and
adapt its providers.base to LLMClient.

Pros: zero extraction risk; all stage code arrives at once.
Cons: vendored provider ABC conflicts with the existing two-outlet client
(two parallel LLM paths); duplicated dataclasses and logging; users editing
prompts must edit Python files; large dead surface (foundry provider,
formatters) we do not want; harder to keep the Dash UI state machine in sync.

### 1.3 Decision

Pick Option A. Rationale in one line: the proven value is the 22 prompt
templates plus the stage sequencing/compliance regex, all of which are data
or small logic, while the app already owns provider transport via
src\llm_client.py; importing data and rewriting thin glue is strictly simpler
than vendoring and reconciling two provider stacks.

## 2. Stage Mapping: Real S1-S7 onto the Existing Pipeline

Existing src\pipeline.py pseudo-stages:
upload -> parse -> rules -> agent_citation -> agent_apa -> agent_sme -> summary.

Existing src\review_agents.py: a chunked 3-agent engine (citation, APA, SME)
that feeds agent_citation/agent_apa/agent_sme.

Proposed mapping (keep existing stage NAMES for UI/state compatibility; change
what each stage EXECUTES when engine_mode == "seven_stage"):

| Pipeline stage name | Executes (7-stage mode) |
|---------------------|--------------------------|
| upload              | unchanged (file intake)  |
| parse               | unchanged, but also produces the full plaintext "document" artifact that S1 stores |
| rules               | S1 Extract + deterministic compliance regex pass (compliance.py port) + S2 Cross-Section are driven from here; stage emits findings and carries parsed sections forward in state |
| agent_citation      | S3 Citations + APA check (unified branch prompt, one call per branch group) |
| agent_apa           | S4 SME + Stats check |
| agent_sme           | S5 CopyEdit + Bias + Originality check |
| summary             | S6 Dedup (deterministic, no LLM) then S7 Final Report (1 LLM call) and report rendering |

Notes:
- The parse stage already does document -> text; S1's LLM extraction call is
  attached to the rules stage execution block to keep the number of visible
  UI stages constant. Internally the engine module exposes run_s1..run_s7 in
  the true order; pipeline.py simply invokes them from the mapped slots.
- src\review_agents.py (chunked 3-agent) is RETAINED as engine_mode
  "legacy_chunked" behind a config flag so the old path keeps working; the new
  engine_mode "seven_stage" is the default after G1 acceptance. No code in
  review_agents.py is deleted in G1.
- engine_mode lives in the app config (configs\app_config.json or existing
  config mechanism; runbook step b.3 pins the exact file).

## 3. Prompt Store Schema: configs\prompts.json

Top level:

{
  "schema_version": 1,
  "source": "asksage_workflow_v3_clean.json",
  "imported_at": "<ISO8601 date>",
  "stages": { ... }
}

"stages" keys: "s1_extract", "s2_cross_section", "s3_citations",
"s4_sme", "s5_copyedit", "s6_dedup", "s7_report".

Each stage object fields:

- "model": string, verbatim config.model from the source workflow node
  (e.g. the model the node used). The loader may override at call time via
  the outlet config; the stored value is the proven default.
- "temperature": float, verbatim config.temperature from the node.
- "max_tokens": integer, sane per-stage default (4096 for S1-S5 analysis
  stages, 8192 for S7 report) since the workflow JSON may not carry one.
- "system_prompt": string; the system/role text if the node separates it,
  else "" and the full text stays in prompt_template.
- "prompt_template": string, byte-identical prompt_template from the node
  (unified branch prompt where the workflow used one). Placeholders use the
  source convention, e.g. {document}, {section}, {branch}; see
  "file_variables".
- "file_variables": list of strings, the placeholder names the template
  expects (e.g. ["document"]) so the loader can validate render inputs.
- "version": integer, starts at 1.
- "updated_at": ISO8601 string, set at import and on any edit.

There are 22 prompt_template entries total across the 7 stages (stages with
branch variants store the variants under an additional "variants" list of
objects {name, prompt_template, file_variables}; the unified branch prompt
optimization means most stages have exactly one entry). The loader exposes
get_prompt(stage_id, variant=None).

## 4. provider.complete vs LLMClient.chat_completion

pubs_review providers.base defines provider.complete(prompt, model,
temperature, max_tokens) over whole documents; AskSageProofAgent_Local's
LLMClient.chat_completion(messages, provider, model, temperature,
max_tokens) takes a messages list.

Adapter rule: the new engine calls LLMClient with
messages=[{"role":"system","content":system_prompt},
{"role":"user","content":rendered_template}] and lets LLMClient route to the
configured outlet ("local"/Maple by default, "custom" when set).

Chunking tradeoff (Maple context window unknown):
- The proven pipeline runs ~10 whole-document calls and worked on
  research-plan-sized manuscripts (tens of pages). Whole-document preserves
  the proven prompt behavior exactly (cross-section prompts reference the
  full text) and is the DEFAULT.
- The legacy chunked path exists only in review_agents.py and is not used by
  the 7-stage engine.
- Guardrail: before each call, estimate tokens as len(text)/4; if the
  rendered prompt exceeds a configurable ceiling (default 24000 tokens,
  configs\app_config.json key "seven_stage.max_prompt_tokens"), fall back to
  section-wise calls for that stage only (split on the parse stage's section
  boundaries, run the same template per section, merge findings). This keeps
  behavior identical for normal documents and safe for oversized ones. Do
  not implement a summarization-based map-reduce in G1.

## 5. Severity + Domain Schema

Every finding object emitted by S2-S6 (and consumed by S7) uses:

{
  "id": "<stage>-<seq>",
  "stage": "s2|s3|s4|s5|s6",
  "severity": "CRITICAL|MAJOR|MODERATE|MINOR",
  "domain": "<see list>",
  "location": {"section": "<heading or 'N/A'>", "quote": "<verbatim text snippet>"},
  "issue": "<one-sentence description>",
  "recommendation": "<concrete fix>",
  "source": "llm|regex"
}

Severity mapping from the proven output: the v3 prompts already ask for
severity words; the engine normalizes to the four levels above
(anything else maps: "blocker"/"fatal" -> CRITICAL, "important" -> MAJOR,
everything unknown -> MODERATE). The compliance regex pass emits findings
with source "regex" and severity from its own label map (fail-level labels ->
CRITICAL/MAJOR, warn-level -> MODERATE).

Domain enum (string, normalized lowercase): "citations", "apa_style",
"statistics", "methodology", "copyedit", "bias", "originality",
"compliance", "structure", "other". S3 emits citations/apa_style; S4 emits
statistics/methodology; S5 emits copyedit/bias/originality; regex pass emits
compliance; S2 emits structure or other; S6 emits "other" with issue text
prefixed "Duplicate finding: ".

S7 report groups findings by severity (CRITICAL first) then domain, and the
report header repeats the counts. The S7 prompt_template already produces a
markdown report; the engine renders the severity/domain table deterministically
above the LLM narrative so the schema is enforced even if the LLM deviates.

## 6. Failure and Degradation Rules

- Any stage LLM call failing after 2 retries (LLMClient-level) marks the
  pipeline stage failed; pipeline.py already has per-stage error state; keep
  that behavior.
- If prompts.json is missing or a stage key is absent, the loader falls back
  to hardcoded prompt strings baked into src\prompts_fallback.py (same
  content, generated at import time by the extraction script). This makes the
  app runnable even if a user corrupts the JSON.
- S6 dedup is deterministic only; it never calls the LLM.
