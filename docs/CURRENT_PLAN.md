# AskSage Proof Agent - Current Execution Plan (Audit Copy)

> Status: SUPERSEDED - historical planning record. The engine decision below
> (Maple-Preview) was replaced by the Bonsai-1.7B local engine; see
> DEPLOY.md and QUICKSTART.md for the current stack. This document is kept
> for provenance only.
> Last updated: 2026-09-12
> Author: DeepSeek Harness coding agent (planning rounds on high-intelligence models)
> Project root: `C:\Users\haiji\Documents\AskSageProofAgent_Local`
> Provenance source: `C:\Users\haiji\Documents\DAPAM_OCR` ("Pubs Review Agent v3")

ALL CHAT, CODE, COMMENTS, AND DOCS ARE ENGLISH / ASCII ONLY (iron rule):
no emoji, no em-dashes, no non-ASCII. The boss speaks English only.

---

## 1. Purpose

Replicate and run the proven AskSage "Pubs Review Agent v3" workflow locally,
delivering:

1. An **agent that runs through end to end** (the proven 7-stage review
   pipeline producing an APA 7 + ARI editorial report).
2. A **clean local model stack**: Maple-Preview is the ONLY local model, and
   the frontend -> backend -> model -> frontend conversation completes.
3. A **new UI that passes audit** (AskSage/n8n-style canvas), meeting the
   boss's need for transparency and control over every node's model and prompt.

---

## 2. Working Protocol (every goal)

Three planning rounds on a high-intelligence model (GPT / GLM 5.3 / Claude),
then one execution round on DeepSeek Flash, then independent verification.

| Round | Model class | Output |
|---|---|---|
| Plan R1 - Facts | High-intelligence | Document/code analysis, constraints, open questions |
| Plan R2 - Design | High-intelligence | Options compared, architecture chosen, risks |
| Plan R3 - Runbook | High-intelligence | Step-by-step execution plan + acceptance criteria |
| Execute | DeepSeek Flash | Run the runbook verbatim, report deviations |
| Verify | High-intelligence | Independent QA of the execution report |

Planning docs are written to `docs/plans/<goal>-R<n>.md`.

---

## 3. The Three Goals

### Goal 1 - Run the Pubs Review Agent end to end (the "run it through" goal)

Adopt the proven 43-node AskSage workflow into the local app:

- Import all 22 verbatim prompts to `configs/prompts.json`.
- Rebuild the engine as the proven 7-stage sequential pipeline.
- Keep the PRD optimizations (compliance via regex, unified branch prompt).
- Wire to the two-outlet LLM client (Maple local + custom fallback).
- Findings gain `severity` (CRITICAL/MAJOR/MODERATE/MINOR) and `domain`.

### Goal 2 - Models clean, whole stack talking

- Maple-Preview is the only local model (llama-server via deepgrove fork).
- Full conversation path: frontend -> backend -> Maple -> frontend.
- Purge ALL Ollama containers/images/volumes; report freed disk.

### Goal 3 - New UI passes audit

- AskSage Agent Builder-style canvas: nodes, ports, animated edges, inspector,
  pan/zoom, Activity panel, prompt editor (model + prompt version per node).
- Must pass formal design + accessibility audit with zero open critical/major.

### Goal 3 status: MET (canvas UI built + audits passed)

AskSage Agent Builder-style canvas implemented on top of the proven engine:

- Python-rendered SVG canvas (Dash 4.4.1 has no html.Svg, so SVG markup is
  injected via dcc.Markdown dangerously_allow_html) with 7 node cards (Upload,
  Parse, Rules, Citation, APA, SME, Summary), 8 bezier edges, agents stacked on
  a lane, pan/zoom/reset, node drag-to-move, position persistence across the 1s
  tick (MutationObserver re-apply), and arrow-key roving focus.
- Node inspector: click/keyboard opens it with model, temperature, max_tokens
  and the FULL prompt text from configs/prompts.json; Save writes atomically
  (tmp + os.replace), bumps version + updated_at, and is blocked mid-run. This
  is the boss's controllability requirement.
- Activity panel (aria-live) streams stage status; Export workflow JSON
  downloads stages + edges + layout. List-mode toggle reuses the original strip
  and is forced below 560px.
- Interaction listeners bound once on #canvas-viewport (delegation) with a
  data-bound guard; clientside callbacks via dash_clientside.
- Files: dashboard.py (canvas layer), assets/canvas-clientside.js (new),
  assets/style.css (G3 section, tokens only, no hex), tests/test_canvas.py.

Independent audit (tools/audit_g3.py): 16/16 PASS (ASCII gate, no hex in G3
CSS, protected files untouched, dashboard imports, callbacks grew, /health,
clientside JS balanced). test_canvas.py 6 PASS. Full suite green.

Formal design + accessibility audit: docs/G3_AUDIT.md - PASS with zero open
critical/major findings (WCAG AA considerations: 44px targets, keyboard nodes,
roving, aria-labels, list-mode fallback, reduced-motion).

### G3 fix: empty canvas + misalignment (post-audit repair)

The first canvas render came up empty and off-grid. Root causes found and
fixed:

1. Empty viewport: dcc.Markdown(dangerously_allow_html=True) runs the markup
   through a markdown renderer that lowercases <foreignObject> to
   <foreignobject>; SVG is case-sensitive and ignores the lowercased tag, so
   every node card disappeared (only faint hairline edges remained). Fix: the
   SVG markup now ships through store-canvas-svg and is injected with raw
   innerHTML by a new canvas.renderSvg clientside callback, which preserves
   the markup byte-exact. Dash 4.4.1 html components reject the
   dangerouslySetInnerHTML prop, so the store + clientside route is the only
   clean injection path.
2. Misalignment: #canvas-region had no width container while the rest of the
   page centers at 1180px. It now uses the same max-width/margin/padding
   container as .page and .pipeline-window.
3. Activity log looked like raw text. Lines are now structured rows:
   time (muted) + stage title + status word colored by state.

Dashboard live at http://localhost:8501 with Canvas + List (strip) views;
Maple engine live on http://localhost:8080.

---

## 4. Proven Source Assets (found during analysis)

`DAPAM_OCR` is the previous successful build, "Pubs Review Agent v3".

| Asset | Location | Value |
|---|---|---|
| 43-node AskSage workflow JSON | `DAPAM_OCR\asksage_workflow_v3_clean.json` | 22 LLM + 18 var + 3 decision-tree nodes, 48 edges, all prompts+models verbatim |
| PRD | `DAPAM_OCR\docs\PRD.md` | Requirement: 3 inputs (manuscript, ari_publication_manual, army_ar_rag), 7-stage flattening, severity/compliance design, provider parity |
| Reference Python pipeline | `DAPAM_OCR\pubs_review\` | 7 stages, prompts extracted, compliance regex, provider ABC |

The original workflow's inputs include three gate documents the boss
mentioned: **DTIC pub regulations, ARI internal publication manual, and Army
publication regulations**. They were uploaded to the AskSage platform; they are
NOT present as files on this machine (searched the workspace). The distilled
rules are embedded verbatim in the imported prompts; the originals can be
added to `data/reference/` later.

---

## 5. Architecture Decision (locked in R2)

**Option A** (chosen): Import the 22 verbatim prompt templates into
`configs/prompts.json` as a single editable, versioned store; re-implement the
thin 7-stage glue natively in `src/`; port the compliance regex. This reuses
the existing two-outlet `LLMClient` and does NOT vendor `pubs_review` (which
would duplicate the provider stack).

- Prompt schema per stage: `model, temperature, max_tokens, system_prompt,
  prompt_template, file_variables, version, updated_at`; branch variants under
  `variants`.
- LLM calls are whole-document (proven behavior) with a token-guard fallback
  to per-section calls for oversized documents (Maple context window unknown).
- `review_agents.py` (legacy chunked 3-agent) is retained behind an
  `engine_mode` flag; the new default is `seven_stage`.
- Findings schema: severity CRITICAL/MAJOR/MODERATE/MINOR + domain enum;
  an adapter maps these to the existing app schema
  (agent, severity error/warning/info, location, original_text, issue,
  suggested_fix, source) so one findings board renders both engines.

---

## 6. Maple Engine (Goal 2)

- Model: `deepgrove/maple-preview-GGUF`, TQ2_0 + Q4_K head, 5.5 GiB.
  Download verified: `models\maple-preview-TQ2_0-head-Q4_K.gguf` (GGUF header OK).
- Runtime: deepgrove llama.cpp fork, `llama-server`, OpenAI-compatible API.
- Serve paths:
  - Path A (fast): Docker image `maple-llm-server` (built, exit 0) on port 8080.
  - Path B (reliable fallback): WSL2-native build (bypasses flaky Docker
    Desktop). WSL access currently DENIED in this shell (needs elevation).
- Fork cloned at `.\llama.cpp`. Native Windows toolchain ABSENT (no CMake/gcc/MSVC).
- `configs/.env` pinned to `LOCAL_MODEL=maple-preview`, `LOCAL_API_BASE=http://localhost:8080/v1`.
- Connection-probe bug already fixed (accepts any non-empty reply).
- Maple uses `--jinja` (embedded chat template incl. thinking prefix); the
  client already strips ` thinking` blocks via `normalize_model_output`.

### Goal 2 status: MET (Maple live + Ollama purged)
- `maple-llm-server` container running on port 8080, healthy
  (`docker ps` status = `Up ... (healthy)`, `/health` = 200).
- Served model id: `/models/maple-preview-TQ2_0-head-Q4_K.gguf`
  (`configs/.env` `LOCAL_MODEL` aligned to it).
- Key fact: Maple exposes `n_ctx_train = 131072` (131K context), so
  whole-document stage calls run without chunking (proven design assumption).
- `test_connection` = True; live S3 (Citations+APA) run on the ACSO sample
  returned a real `NON_COMPLIANT` label + parsed finding in ~267s (CPU, 20B MoE).
- Dashboard relaunched with Maple env; `/health` 200, `/` 200, pipeline region present.

Docker cleanup (before -> after):
- Containers: 4 -> 1 (only `maple-llm`; removed gifted_sinoussi, sharp_boyd, gifted_moser).
- Images: 9.13 GB -> 4.09 GB (removed ollama/ollama:latest 5.04 GB).
- Volumes: 7.7 GB -> 92.84 MB (removed 4 stale ollama model volumes).
- Engine remained healthy throughout.

Still present (flagged, not deleted without consent): `asksageproofagent_local-streamlit-app:latest` (632MB, retired Streamlit image), `army-officer-job-profiler` (unrelated), build cache 5.84 GB.

---

## 7. Goal 1 Progress (core DONE, tested)

Deliverables created/verified:

| File | Purpose | Test |
|---|---|---|
| `configs/prompts.json` | 22 verbatim prompts (7 stages), ASCII-clean, versioned | round-trip + ascii, PASS |
| `src/prompts.py` | Prompt store loader + hardcoded fallback + stage summary | test_prompts.py 11/11 |
| `src/pub_pipeline.py` | 7-stage engine (S1-S7) + compliance regex + severity/domain + app-schema adapter | test_pub_pipeline.py 9/9 |
| `tools/build_prompts_json.py` | Reproducible prompt extraction | run + ascii, PASS |
| `docs/plans/G1-R2-design.md` | Architecture decision | - |
| `docs/plans/G1-R3-runbook.md` | Execution runbook + 11-item acceptance | - |

Pipeline verified on `data\ACSO-Research-Plan-V1.1.docx` (9,365 words): all 7
stages run, per-domain compliance verdicts produced (stub LLM; real findings
require the live engine in G2).

Full test battery (all green, no regressions):
- test_prompts.py: 11 PASS
- test_pub_pipeline.py: 9 PASS
- test_pipeline.py: 16 OK
- test_runner.py: 8 OK
- test_review_agents.py: 20 PASS
- test_llm.py: ALL PASSED (skips not counted)
- All new source files ASCII-clean.

### Remaining G1 work
- Live end-to-end run on Maple (needs G2).

### G1 integration (added)
- `src/pub_pipeline.py` now exposes a `run_review(text, ...)` facade with the
  identical signature to the legacy engine: runs deterministic rules first,
  then the proven S1-S7 pass when an llm_client is given, and returns the
  shared `{findings, summary, agents_run, skipped, notes}` shape with
  app-schema findings.
- `dashboard.py` engine swap is now env-driven:
  `REVIEW_ENGINE=pub_pipeline` (new default, the proven 7-stage engine) or
  `REVIEW_ENGINE=review_agents` (legacy chunked). Zero callback changes; the
  16 callbacks and `/health` are intact. Verified: dashboard imports, layout
  builds, `_call_review_engine` path works against the facade (deterministic
  rules produce findings; 3 LLM passes skip cleanly without a client).

---

## 8. Test and Verification Method

- Unit suites via project venv: `C:\Users\haiji\Documents\AskSageProofAgent_Local\.venv\Scripts\python.exe`.
- ASCII gate: scan every source file, must report empty non-ASCII.
- `ast.parse` on dashboard.py.
- Browser walkthrough for UI (G3).
- Independent re-verification of every agent self-report (never trust
  execution self-reports blindly).

---

## 9. Risks and Fallbacks

| Risk | Response |
|---|---|
| Docker daemon down | WSL2-native serving; or user starts Docker Desktop |
| WSL denied in shell | user starts it / reboot; native toolchain absent so no Windows compile |
| Maple context window small | token-guard fallback to per-section calls (config toggle) |
| Maple quality below gpt-5.1-gov | judge on ACSO sample; custom-outlet/Foundry fallback stays wired |
| Prompt drift | byte-identical extraction + automated diff vs source JSON |
| Gate documents absent | prompts carry distilled rules; UI marks "not loaded"; add to data/reference/ later |

---

## 10. Docker packaging (completed after G3)

- `requirements.txt` rewritten to the real Dash app deps (dash 4.4.1,
  plotly, flask, gunicorn, openai, python-dotenv, PyPDF2, python-docx) -
  was the stale Streamlit/pandas/requests list.
- `Dockerfile.app` rewritten: python:3.11-slim, installs the requirements,
  copies dashboard.py/app.py/src/configs/assets, serves via gunicorn
  `dashboard:app.server` on :8501, healthcheck on /health,
  LOCAL_API_BASE -> http://maple-llm:8080/v1, REVIEW_ENGINE=pub_pipeline.
- `docker-compose.yml` rewritten: `maple-llm` (image maple-llm-server, host
  ./models bound read-only, serves on 8080 with --jinja) + `dash-app`
  (build, port 8501, depends_on maple-llm healthy). No Ollama anywhere.
- `wsgi.py` added: exposes `application = dashboard.app.server`; gunicorn
  loads it as `wsgi:application` (gunicorn 26.2.0 rejects `dashboard:app.server`).
- `QUICKSTART.md` rewritten to the Maple + Dash reality.
- All ASCII-clean; `docker compose config` validates (exit 0).

Validation: app image built and booted under gunicorn in a container;
`/health` -> 200 and the served layout contains `canvas-region` (the full
Dash app runs in Docker). Images present: `ask-sage-proof-agent` and
`maple-llm-server`.

## 11. Rebuild: 7-node accordion List view - DONE and live

The rebuild replaced the canvas with a single 7-node List view (default) and
unified the run flow onto the proven 7-stage engine. All verified live.

- src/pipeline.py stages renamed to s1_extract..s7_report; AGENT_STAGES =
  s3_citations/s4_sme/s5_copyedit. test_pipeline 16 pass.
- src/runner.py rewritten: ReviewRun(llm_client, selected=[stages],
  pipeline=...) drives pub_pipeline stage-by-stage on a daemon thread; s6/s7
  auto-run after a gated stage; unselected gated stages become "skipped";
  findings normalized to the app schema; report_text() added. test_runner 8 pass.
- src/pub_pipeline.py composes each stage prompt with its attached reference
  documents (configs/references.json + src/references.py): the per-node RAG
  feed (ARI manual, Army AR/RAG, DTIC regs).
- src/stage_meta.py: display titles, badges, sub-step flow manifest
  (Analyze -> Compliance label -> Branch 3-way -> Final format).
- configs/prompts.json: every stage carries model/temperature/max_tokens/
  references/version/updated_at; save round-trip verified (version bump,
  atomic write, edits persist).

Dashboard (dashboard.py 3135 lines, 17 callbacks):
- Canvas fully removed: assets/canvas-clientside.js, G3 CSS block,
  tests/test_canvas.py, tools/audit_g3.py, canvas renderers + callbacks +
  clientside registrations all deleted. /_dash-layout has zero canvas refs.
- List view is the only view (7 original stage titles visible in the strip).
- Clicking a node opens the accordion body in stage-detail: sub-step flow with
  every prompt editable, plus model / temperature / max tokens inputs and the
  attached reference documents (with loaded/not-loaded state).
- Run flow unified: run_selected_agents / rerun_agent / pip_progress_tick now
  drive the 7-stage runner (persona names map to gated stages).

Live proof (Maple, CPU):
- Full S1-S7 run completed (1392s ~ 23 min): S1/S2/S3 done, S4/S5 skipped
  (deselected in the test), S6/S7 done, final report generated.
- First attempt surfaced the CPU timeout: LLM_REQUEST_TIMEOUT raised
  240 -> 900s (configs/.env + .env.example) so a slow 20B CPU call is not
  mistaken for failure.

Tests: pipeline 16, runner 8, references 5, stage_meta 4, prompts 11,
pub_pipeline 11, review_agents 20 = 75 green; ASCII clean on all files.
Dashboard live at http://localhost:8501, Maple at :8080.

## 13. Additions round 2 (approved plan): attachments, guidance, review fixes, engine swap

All done and verified (78 tests green):

- **Editable reference attachments (Part 1):** each stage's reference list is
  now a checklist (dcc.Checklist, id type ref-attach) pre-checked from the
  stage's `references` field; Save persists the selection atomically with a
  version bump; disabled mid-run. No more grayed-out area.
- **Custom API guidance (Part 2):** collapsed html.Details "How to connect
  your own API (plugin / util config)" in the Engine panel: what the outlet
  is, the three values (base URL /v1, exact model, key), where to set them
  (env wins over configs/.env), verify via Test connection, fallback, per-node
  model choice. Delimited HOPOVER-DOCS placeholder ready for pasted vendor
  docs. One-line pointer in the node prompt editor.
- **Code-review fixes (F1-F8, from desktop-app-engineer + codebase-archaeologist):**
  - F1 (Critical) pip_stage_focus now also writes store-inspector-stage; the
    save callback was previously dead in the running app. Regression test added
    (test_dashboard_save.py).
  - F2 save maps values by key (ctx.states_list), not positional zip.
  - F3 progress label s2_cross_section (was "rules").
  - F4 cancel copy: "stage boundary" (was "chunk boundary").
  - F5 QUICKSTART.md: dropped deleted test_canvas + Canvas-view claims.
  - F6 pipeline.py docstrings now name s2_cross_section / s7_report.
  - F7 app binds 127.0.0.1 by default (env ASK_DASH_HOST to share LAN).
  - F8 dead code removed (_CANVAS_MODE, REVIEW_TEMPERATURE, gated_ran,
    identity STAGE_TO_PROMPTS_KEY); stage runner budgets now read the editable
    per-stage config (max_tokens/temperature) instead of hardcoded values.
- **Engine swap to Bonsai-1.7B (Part 4, user-selected):**
  - Model: prism-ml/Bonsai-1.7B-GGUF Q1_0, 0.24 GB, 1.7B params, 32,768-token
    context (vetting confirmed via /v1/models meta), conversational chat
    template (--jinja), Apache 2.0 (note: base lineage is Qwen3-1.7B - policy
    flag recorded).
  - Served by the existing maple-llm-server image: --alias bonsai-1.7b,
    -c 16384, -t 8. LOCAL_MODEL=bonsai-1.7b.
  - vetting gate PASSED: real S3 run on the ACSO manuscript produced 12
    structured findings; S1+S2+S3(+S6) completed in ~14 min (vs Maple's ~23
    min for a smaller scope). Bound modes decode at ~20-27 tok/s; unbounded
    rambling at ~7.8 tok/s is why per-stage max_tokens were tightened
    (1024-2048 + Bonsai-suggested temperatures).
  - Maple GGUF still on disk for swap-back; QUICKSTART documents the path.

## 12. Still out of scope

- Free-form node graph EDITING (add/delete/re-wire nodes) - out of scope.
- The three gate documents as local files: add to data/reference/ when the
  boss supplies them (the registry marks them "not loaded" until then).
- Custom API outlet work (named by the user as a later goal).
