# G3 Design + Accessibility Audit Report

> Goal 3: AskSage Agent Builder-style canvas UI must pass audit with zero open
> critical/major findings.
> Date: 2026-09-12
> Auditor: DeepSeek Harness coding agent (independent of the G3 execution agent)
> Project: AskSageProofAgent_Local
> Status: PASS (zero open critical/major findings)

All audit evidence below was gathered by the auditor directly from the served
layout, the source files, and the running test suite - it does not rely on the
execution agent's self-report. English/ASCII only. The running dashboard is at
http://localhost:8501 with the Maple engine on http://localhost:8080.

---

## 1. Functional audit

| Check | Method | Result |
|---|---|---|
| 16 existing callbacks preserved | dash import + callback_map count grew (16 -> more), no existing Output/Input altered | PASS |
| /health 200 | curl /health while dashboard running | PASS |
| app starts clean | dashboard.py background run, / 200 | PASS |
| Canvas serves 7 nodes / 8 edges | /_dash-layout contains 8 data-src edge paths, 7 node groups (data-stage), 7 foreignObjects | PASS |
| SVG markup | viewBox present, bezier `d` paths | PASS |
| Prompt inspector loads prompts.json | STAGE_TO_PROMPTS_KEY maps to real keys (s1_extract..s7_report); s4_apa->s4_sme, s5_apa->s5_copyedit corrected | PASS |
| Save writes atomically + bumps version | runbook: tmp + os.replace, version += 1, UTC updated_at | PASS (code review + runbook compliance) |
| Save blocked mid-run | inspector-save callback rechecks active run (same check as Cancel) | PASS (code review) |
| Activity panel | canvas-activity present, aria-live=polite | PASS |
| Export JSON | canvas-download via dcc.send_string, stages+edges+layout | PASS (code review) |
| List-mode fallback | canvas-region toggle + CSS mode-canvas/560px | PASS |
| Protected files unmodified | src/pipeline.py, runner.py, prompts.py, app.py: zero 'canvas' refs; prompts.json version 1 unchanged | PASS |
| All test suites green | test_canvas 6, prompts 11, pub_pipeline 11, pipeline 16, runner 8, review_agents 20, llm all | PASS |

## 2. Design audit (paper-and-ink system)

| Check | Method | Result |
|---|---|---|
| Zero emoji | ASCII scan all touched files | PASS |
| No em-dashes / non-ASCII | ASCII scan (all ord > 127 empty) | PASS |
| No hex color literals in G3 CSS | regex '#[hex]{3,8}' over G3 CSS section | PASS (only tokens used) |
| Single accent, radius tokens | CSS uses var(--accent), var(--radius), 999px pill badge | PASS |
| Fonts | Source Serif 4 titles, Public Sans body | PASS |
| No gradients except sanctioned dot-grid | G3 CSS: single radial-gradient dot grid (background-image), no linear/other gradients | PASS |
| Layout | nodes in lane, agents stacked, zoom/pan/reset controls | PASS |

## 3. Accessibility audit (WCAG 2.x AA considerations)

| Check | Method | Result |
|---|---|---|
| Keyboard-focusable nodes in order | servers 7 x tabindex=0 on node cards | PASS |
| Arrow-key roving | canvas-clientside.js rovingFocus (ArrowRight/Down next, Left/Up prev) | PASS |
| Enter opens inspector, Esc closes | nodeInteract keydown handler + Escape sets store to null | PASS |
| Full aria-label on nodes | server: 10 aria-label (7 nodes + controls), "Stage N of 7, title, badge, status" | PASS |
| role=button on nodes | 22 role=button (nodes + buttons) | PASS |
| Touch targets >= 44px | CSS min-height:44 (x5), buttons | PASS |
| Status text + color, never color alone | canvas-node-badge text (RUN/OK/FAIL/...) + status- class | PASS |
| prefers-reduced-motion | CSS 2 rules disable edge-flow + progress animations | PASS |
| aria-live for Activity | canvas-activity aria-live=polite | PASS |
| List-mode fallback forced below 560px | CSS @media 559-560px hides mode-canvas, shows strip | PASS |
| Inspector inputs labeled | input labels + char count (aria-describedby) per runbook | PASS |

---

## 4. Result

Goal 3 audit: **PASS**. Zero open critical or major findings. All functional,
design-system, and accessibility acceptance criteria are satisfied. The client-
side JS hardening (once-bound DOM listeners, edge redraw math, zoom clamp,
layout re-apply after server ticks) is in place; the runbook's documented Dash
4.4.1 deviations (SVG via dangerously_allow_html dcc.Markdown, raw DOM
listeners instead of n_keydown) were applied and are noted in the execution
report.

## 5. Known minor follow-ups (non-blocking)

- The canvas List view uses the original strip renderer (unchanged) - good.
- Export JSON schema is download-only (no re-import) - matches scope.
- Browser automated test (Playwright) for drag/pan/zoom is recommended for a
  future hardening pass but is not required for acceptance; interaction was
  verified structurally and via the clientside JS logic review.
