# G3-R2 Design: Agent Builder Canvas for the AskSage Proof Agent

Scope: Goal 3 of docs/CURRENT_PLAN.md. Add an AskSage Agent Builder-style canvas
to the existing Dash dashboard without touching the state layer
(src/pipeline.py, src/runner.py) or any of the 16 existing callbacks.
This document is design-only. Execution steps live in G3-R3-runbook.md.

---

## 1. Architecture decision: Python-rendered SVG + clientside JS vs custom Dash React component

### Option A: html.Svg graph rendered in Python, pan/zoom/drag in one clientside JS file

The canvas is a plain Dash component tree:

- `html.Div(id="canvas-viewport")` - the pannable/zoomable viewport.
- `html.Svg(id="canvas-svg")` - contains one `html.G(id="canvas-edges")` with
  `svg.Path` elements for edges, and one `svg.G(id="canvas-nodes")` with
  `svg.ForeignObject` nodes (each foreignObject holds real HTML: category
  stripe div, type badge, title, port dots). foreignObject lets us keep using
  the existing CSS tokens, Source Serif 4 / Public Sans fonts, and real
  focusable buttons/inputs inside nodes.
- One static file `assets/canvas-clientside.js` (auto-served by Dash) that
  implements pan (pointer drag on viewport background), zoom (wheel with
  ctrl/meta or wheel-on-canvas, clamped 0.4x to 2.0x), node drag (pointerdown
  on a node updates its x/y in the SVG coordinate space and rewrites the
  affected edge paths locally), and writes the resulting positions into
  `store-canvas-layout` via a Dash clientside callback.

### Option B: custom Dash React component (dash-generate-components)

Would require the Node toolchain, `dash-generate-components` (which is already
present in .venv/Scripts, but still needs npm/webpack on the build machine),
a package.json, a React build step, and a rebuild for every change. It gives
cleaner drag state (React refs instead of DOM mutation) and smoother 60fps
drag, but at real cost: new build dependency, new failure surface, and a
component that the rest of the 2,900-line dashboard cannot render or inspect
from Python.

### Weighing Dash constraints

| Constraint | Option A impact | Option B impact |
|---|---|---|
| clientside callbacks | One file, no build step; used for drag/zoom which is pure client state | Not needed; component owns its JS |
| suppress_callback_exceptions (already True) | New ids follow the same pattern; no change needed | Same |
| allow_duplicate outputs | New stores get their own outputs; existing pip-progress allow_duplicate pattern untouched | Same |
| Serialization | Positions persist in a dcc.Store as plain JSON dict; trivially exported | Same |
| State sync with server (statuses each poll tick) | Python re-renders node props each tick; clientside JS must not clobber them - solved by separating "positions" (client-owned, in store-canvas-layout) from "statuses" (server-owned, in store-pipeline) | Component would need its own props contract |
| Toolchain | Zero new dependencies | Node + npm + webpack required to build |
| Debuggability | Plain DOM in the existing page; F12 shows everything | Bundled component, harder to hot-debug |
| Risk to the 16 existing callbacks | None: purely additive ids | Small: a broken bundle breaks the whole page |

### Decision: Option A

Justification:

1. The graph is small and static in topology: 7 nodes, 6 to 8 edges, fixed
   set. It never needs virtualization or a graph layout engine. React adds
   toolchain weight with no scale payoff.
2. Execution is owner-bound: drag/zoom must never round-trip the server. A
   single clientside JS file inside assets/ is the sanctioned Dash way to do
   this with no build step, and the codebase already relies on Dash auto-
   serving assets/ (assets/style.css, assets/fonts).
3. All server interaction (statuses, prompt editing, export) stays in normal
   Python callbacks, exactly like the existing 16. The canvas is "dumb DOM +
   two stores", so the risk of breaking existing behavior is near zero.
4. foreignObject gives us real HTML nodes (badges, focus rings, aria labels,
   44px hit areas) so accessibility is plain HTML/CSS, not SVG arcana.

Hard rule for the executor: clientside JS never mutates status text, badges,
or edge classes that the server renders. It only moves node groups (transform
attribute) and redraws edge `d` attributes from cached geometry. On any
server re-render of a node's inner content, the JS re-applies the stored
transform from store-canvas-layout (listen via a MutationObserver-free
approach: after each Dash render cycle, re-apply transforms from the layout
store; simplest robust hook is a `dash_clientside` callback on the store
itself).

---

## 2. Component and data-flow design

### 2.1 New ids (all additive, none collide with the 16 existing callbacks)

Components:

- `canvas-toggle` - dcc.RadioItems or html.Button group: "Canvas" / "List".
  Default Canvas on viewports >= 560px, List below (CSS media query + JS
  prefers-list default). Persisted nowhere; per-session only.
- `canvas-region` - html.Div wrapper. Its class `mode-canvas` or `mode-list`
  drives which child is visible. Both children are ALWAYS in the DOM (list
  mode is the a11y fallback and the screen-reader path); only CSS hides one.
- `canvas-viewport` - pan/zoom container (class canvas-viewport).
- `canvas-svg` - the SVG (viewBox fixed 1200x760; CSS scales to fit).
- `canvas-nodes-{stage}` - one svg.G per stage, id `canvas-node-upload`,
  `canvas-node-parse`, `canvas-node-rules`, `canvas-node-agent-citation`,
  `canvas-node-agent-apa`, `canvas-node-agent-sme`, `canvas-node-summary`.
  Each contains a foreignObject with the node card HTML and a visible-focus
  wrapper `tabindex=0 role=button aria-label="..."`.
- `canvas-edge-{from}--{to}` - svg.Path per edge, id pattern
  `canvas-edge-parse--rules` etc.
- `canvas-inspector` - html.Div side panel (right drawer or below-canvas
  panel on narrow screens).
- `canvas-activity` - html.Div log stream panel (see 2.7).
- `canvas-export-btn` - html.Button "Export workflow JSON".
- `canvas-download` - dcc.Download.

Stores:

- `store-canvas-layout` (dcc.Store, memory) - `{"positions": {stage: [x, y]},
  "zoom": 1.0, "pan": [x, y]}`. Written ONLY by clientside JS (positions,
  pan, zoom). Read by Python callbacks when Export is clicked so the exported
  JSON includes layout. Optional localStorage variant decided by runbook
  default: memory (keeps the app stateless per session; layout resets on
  refresh, which is acceptable for a proof agent and avoids stale layouts
  after schema changes).
- `store-inspector-stage` (dcc.Store, memory) - currently inspected stage id
  or null.
- `store-prompts-cache` (dcc.Store, memory) - snapshot of configs/prompts.json
  loaded on page load / refresh button, so the inspector renders without a
  disk read per keystroke. Server reads the file once per cache refresh; file
  remains the source of truth at save time.

### 2.2 Node layout (fixed topology, draggable positions)

Default coordinates in the 1200x760 viewBox (node card 220x96, agent cards
may grow to 220x120):

- upload:      x=60,  y=332 (input port left, output port right)
- parse:       x=360, y=332
- rules:       x=660, y=332
- agent_citation: x=660, y=80   (lane top)
- agent_apa:      x=660, y=332  (lane middle, directly under rules)
- agent_sme:      x=660, y=584  (lane bottom)
- summary:     x=940, y=332

Edges (from -> to):

1. upload -> parse
2. parse -> rules
3. rules -> agent_citation
4. rules -> agent_apa
5. rules -> agent_sme
6. agent_citation -> summary
7. agent_apa -> summary
8. agent_sme -> summary

The 3-agent lane is stacked vertically exactly as the AskSage reference:
rules fans out to the three agent cards, all three fan into summary.
Topological order (VALID_STAGES in src/pipeline.py) is preserved; drag only
changes visual position, never execution order, and the Export JSON records
edges from this fixed list (not from geometry), so a user cannot create a
graph the runner cannot execute.

### 2.3 Port anchor math (bezier edges)

Each node exposes an input port (left edge midpoint) and an output port
(right edge midpoint). Anchor of a node at (x, y) with card size (w, h):

- out port: (x + w, y + h/2)
- in port:  (x, y + h/2)

Bezier path from source out port (x1, y1) to target in port (x2, y2):

    dx = max(40, abs(x2 - x1) * 0.5)
    d = f"M {x1} {y1} C {x1 + dx} {y1}, {x2 - dx} {y2}, {x2} {y2}"

Rendered as svg.Path with `fill="none" stroke=<token> stroke-width=2` and
class `canvas-edge status-<edge-status>`. Edge status is derived server-side
from the two endpoint stage statuses:

- any endpoint failed            -> class status-failed   (stroke --err)
- source done and target pending -> class status-done     (stroke --ok)
- source running OR target running -> class status-running (stroke --accent,
  plus the animated dash class, see 2.4)
- awaiting_approval on either    -> class status-warn     (stroke --warn)
- otherwise                      -> class status-idle     (stroke --hairline)

Status -> CSS class mapping is one small dict in dashboard.py:
`_EDGE_STATUS_MAP`, kept next to `_STAGE_STATUS_CLASS` used by
_render_stage_card today (reuse the same class names status-pending /
status-running / status-done / status-failed / status-skipped /
status-cancelled / status-awaiting-approval so style.css stays consistent).

### 2.4 Running-edge animation (zero server load)

CSS only, applied via class `edge-running`:

    .canvas-edge.edge-running {
        stroke-dasharray: 8 6;
        animation: edge-flow 0.9s linear infinite;
    }
    @keyframes edge-flow {
        to { stroke-dashoffset: -28; }
    }

28 is 8+6 dashed twice so the loop is seamless. No JS timers, no server
ticks beyond the existing 1000ms pip-progress interval that already drives
the strip. Under prefers-reduced-motion the animation is disabled and the
edge is rendered as a solid --accent stroke (accessibility, section 4).

### 2.5 How the pip-progress tick re-renders only what changes

Today the tick callback re-renders `pipeline-region` wholesale. The canvas
follows the same single-writer pattern with finer granularity:

- The existing tick callback (the one at dashboard.py line ~2771 that takes
  `Input("pip-progress", "n_intervals")`) gains ONE additional Output:
  `Output("canvas-svg", "children", allow_duplicate=True)` (duplicates of
  outputs already exist in this codebase; this is a NEW output key so it is
  a plain Output on an id no other callback writes, actually no allow_duplicate
  needed - nothing else writes canvas-svg children).
- That output is computed by a new pure function `_render_canvas_svg(states)`
  mirroring `_render_pipeline_region(states)`. It rebuilds the SVG children.
  This is cheap (7 nodes, 8 paths) and avoids per-node Output plumbing.
- Position preservation during server re-render: the server-rendered node
  groups carry NO transform (or the default layout transform). The
  clientside JS re-applies transforms from store-canvas-layout immediately
  after each render. Mechanism: a clientside callback
  `Output("canvas-svg", "data-layout-applied")`... no - simplest correct
  mechanism: the JS file registers a listener on the viewport element for
  Dash's render cycle by observing `window.dash_callback_context` is not
  available to plain JS; instead use a MutationObserver on #canvas-svg
  (childList, subtree:false is enough since children are replaced wholesale)
  that re-applies stored transforms. MutationObserver is standard DOM, no
  React coupling. This is the ONE place JS touches server-rendered content,
  and it only sets `transform` attributes.
- Drag during a run: allowed for layout; the JS writes positions to
  store-canvas-layout debounced 150ms. Statuses keep flowing independently.

### 2.6 Prompt inspector: read/edit configs/prompts.json

Flow:

1. Click a node (or focus + Enter) -> client sets `store-inspector-stage`
   via a clientside callback (node click is pure client state; no server
   round trip for opening the panel).
2. `store-inspector-stage` is Input to a Python callback that:
   - reads the stage config via src/prompts.py: `find_stage_config(stage_id)`
     (map the inspector's stage id through `normalize_stage_name()` first;
     node ids use pipeline names like agent_citation while prompts.json uses
     s3_citations etc. - normalize_stage_name already bridges this; the
     runbook includes the exact mapping table to verify),
   - writes the inspector panel into `canvas-inspector`: stage title, model
     (dcc.Dropdown or dcc.Input), temperature (dcc.Input number, step 0.1),
     max_tokens (dcc.Input number), and for each key in the stage's `prompts`
     dict a labeled dcc.Textarea (monospace stack, min-height 200px) with the
     full prompt text, plus version and updated_at display.
3. Save button (`inspector-save`) -> Python callback:
   - Input: inspector-save n_clicks, State: all inspector fields,
     store-pipeline (to detect a run in progress).
   - Guard: if the runner is active (reuse the exact condition the existing
     callbacks use to gate Cancel/Re-run, i.e. the run-in-progress signal
     from store-pipeline / runner state that the pip-progress enable logic
     uses), block the save: disable the Save button while any stage status
     is "running" or the pipeline window shows an active run (the button is
     rendered `disabled=True` by the tick-driven inspector refresh too, so
     it cannot even be clicked mid-run; the callback re-checks server-side
     and returns a "run in progress" message as a second line of defense).
   - On save: load configs/prompts.json, apply changes, bump `version`,
     set `updated_at` to UTC ISO, write atomically (write tmp file, os.replace),
     refresh store-prompts-cache, and re-render the inspector with the new
     version. Only fields actually exposed (model, temperature, max_tokens,
     prompt texts) are mutated; handles_chunking and notes are preserved.
   - JSON is ASCII-enforced on write (json.dump with ensure_ascii=True) and
     validated by re-loading with src/prompts.py before replacing the live
     file; a corrupt write never lands.
4. The runner already reads prompts through src/prompts.py at stage start,
   so an edit takes effect on the next run with zero changes to the state
   layer (verified: src/prompts.py get_prompt() is the read path).

### 2.7 Activity panel and run logs

- `canvas-activity` is an html.Div (role="log", aria-live="polite") fed by a
  new Output on the same tick callback: it renders the last N (default 50)
  log lines. Log source: the runner already records progress that the
  pipeline window shows; the Activity panel renders from the same in-memory
  run object the dashboard already reads for the strip (the module-level
  state the tick callback reads today) plus stage-level timestamps
  (started/finished per stage, which StageState already tracks). If per-line
  runner logs are not currently retained in memory, the panel renders
  stage-transition lines (entered/finished/failed/approval requested) built
  from StageState timestamps - decision: stage-transition lines are
  sufficient for Goal 3; do NOT modify src/runner.py.
- Newest lines at the bottom, auto-scroll only if the user is already at the
  bottom (CSS overscroll + tiny JS, same file).

### 2.8 Export workflow JSON

`canvas-export-btn` -> Python callback -> dcc.Download via `canvas-download`:

- Builds a dict:
  {
    "schema": "asksage-proof-workflow",
    "version": 1,
    "exported_at": <UTC ISO>,
    "stages": [ {stage, title, model, temperature, max_tokens, prompts,
                 version, updated_at} ... in VALID_STAGES order, read from
                configs/prompts.json via src/prompts.py ],
    "edges": [ ["upload","parse"], ... fixed 8-edge list from 2.2 ],
    "layout": { "positions": {...}, "zoom": ..., "pan": {...} }  # from
               store-canvas-layout State
  }
- dcc.send_bytes / dcc.send_data with json string, filename
  `asksage-workflow-YYYYMMDD-HHMMSS.json`. ensure_ascii=True.
- No file writes server-side; export is download-only.

---

## 3. Visual design (within the existing token system)

- Node card: background --surface, border 1px --hairline, radius --radius,
  shadow --shadow-card. Left category stripe 4px solid: --accent for LLM
  agent stages (the three agent_* nodes), --ink-muted for mechanical stages
  (upload, parse, rules, summary). Type badge top-right: 10px uppercase
  Public Sans, pill (999px) allowed, e.g. "LLM" on agent nodes, "IO" on
  upload, "STEP" elsewhere. Title in Source Serif 4, 15px --ink; sub-line
  12px --ink-muted (model name for agents, e.g. "local").
- Port dots: 10px circles, --hairline fill, --accent border on hover; must
  be inside the 44px hit area (the whole node is the drag handle, so ports
  are decorative - decision: ports are NOT individually draggable; topology
  is fixed, matching the proof-agent product reality).
- Selected node: border --accent 2px + subtle --accent-dark outline offset.
- Status coloring reuses existing classes: running = --accent border +
  soft progress feel (no gradients; a 3px bottom bar in --accent animated
  width is allowed as it is a solid color), done = --ok check glyph as text
  "OK" badge (ASCII), failed = --err, awaiting_approval = --warn, skipped/
  cancelled = --ink-muted.
- Pan/zoom chrome: bottom-right zoom controls (buttons "-", "100%", "+",
  "Reset"), all 44px targets, --surface on --paper with --hairline border.
- Canvas background: --paper with a 24px dot grid (radial-gradient dots in
  --hairline is a background pattern, not a decorative gradient - approved
  exception; if the audit rejects any radial-gradient, use a repeating
  linear hairline grid instead. Default decision: dot grid via
  background-image radial-gradient 1px dots).
- One accent rule: the only accent-colored elements are running indicators,
  selection, and the primary Save button. Everything else is ink/hairline.

---

## 4. Accessibility design

1. Canvas vs List toggle: `canvas-toggle` buttons with aria-pressed. List
   mode reuses the EXISTING `_render_pipeline_region` strip, untouched - it
   remains the canonical accessible representation. Below 560px viewport
   width, CSS forces list mode (`.mode-canvas { display: none }` inside a
   `@media (max-width: 559px)` block) regardless of toggle state, and the
   toggle itself is hidden.
2. Keyboard: each node wrapper is `tabindex=0 role=button` with
   `aria-label` of the form: "Stage 4 of 7, Citation Agent, LLM node,
   status running, model local. Press Enter to inspect." Arrow keys move
   focus between nodes in topological order (roving tabindex implemented in
   canvas-clientside.js; topological order == VALID_STAGES order, so a
   screen reader walks the pipeline in execution order). Enter/Space opens
   the inspector. Escape closes it.
3. Edges are aria-hidden (decorative; the aria-label carries status
   relationships: the node label includes "feeds Summary" for fan-out
   clarity - decision: keep labels simple, stage + status only; the list
   mode conveys ordering).
4. The SVG has `role="application"` only if arrow-key roving is active;
   otherwise role="group" with aria-label "Pipeline canvas, arrow keys to
   move between stage nodes". Decision: role="group" + instructions in
   aria-label; role=application is avoided (it silences screen reader
   browse mode).
5. Inspector: all inputs labeled (html.Label htmlFor), textareas get
   described-by pointing at a char-count line. Save button disabled state
   announced via aria-disabled and a visible reason string when blocked
   mid-run.
6. Touch targets: every interactive element (nodes, toggle, zoom, save,
   export) is at least 44x44 CSS px hit area; node cards are 220x96 so they
   exceed it trivially; port dots are non-interactive.
7. Contrast: all text uses --ink on --surface or --paper (>= 12:1), muted
   text --ink-muted on --surface >= 6:1; status colors used on borders and
   badges with text in --ink, never as the sole text color. Badges pair
   color with an ASCII word (OK, FAIL, WAIT, RUN, SKIP) so status never
   relies on hue.
8. Motion: @media (prefers-reduced-motion: reduce) kills edge-flow and the
   running bottom bar animation; running state remains visible via the
   solid --accent border and the RUN badge.
9. Zoom is not required for access: list mode shows the same information
   textually, so no content is canvas-only.

---

## 5. What explicitly does NOT change

- src/pipeline.py, src/runner.py, src/prompts.py: read-only for this goal
  (the only writes anywhere are to configs/prompts.json).
- All 16 existing callbacks: zero edits to their Input/Output/State
  signatures. The single permitted touchpoint is APPENDING new Outputs
  (canvas-svg children, canvas-activity children) to the EXISTING
  pip-progress tick callback's declaration and body - this changes that one
  callback, but preserves its existing outputs and behavior exactly; the
  runbook specifies the exact additive diff.
- `_render_pipeline_region`, `_render_stage_card`, `_render_approval_bar`,
  `_render_stage_detail`, `_render_cancel_bar`, `_render_ledger*`: kept
  verbatim as list-mode fallback and reused as-is.
- /health route, app.py, Docker/run scripts: untouched.
