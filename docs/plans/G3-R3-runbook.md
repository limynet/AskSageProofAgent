# G3-R3 Runbook: Agent Builder Canvas Execution (Flash Agent Edition)

Read G3-R2-design.md first for the "why". This runbook is the "what and how",
decision-complete: follow the steps in order, do not improvise, do not touch
files outside the list in Section 1.

Project root: C:\Users\haiji\Documents\AskSageProofAgent_Local\
All paths below are relative to that root. Python is .venv\Scripts\python.exe.

Hard global rules:

- ASCII only in every file you create or edit. No emoji, no em-dash
  (U+2014), no en-dash, no curly quotes, no non-ASCII whitespace. Verify
  with the gate in Section 8 before declaring done.
- English only in comments and UI strings.
- Do not modify: src/pipeline.py, src/runner.py, src/prompts.py, app.py,
  configs/prompts.json (runtime writes only), Dockerfile.app,
  docker-compose.yml, run_local.ps1, any existing test_* file.

---

## 0. Pre-flight (do first, report failures and stop)

1. Run the existing test suite subset and record pass counts:
       .venv\Scripts\python.exe -m pytest test_pipeline.py test_runner.py test_prompts.py -q
   These must pass before and after your changes. If they fail pre-flight,
   STOP and report; do not fix them as part of this goal.
2. Confirm `python -c "import dash"` works in the venv and note the Dash
   version (needed to confirm foreignObject and allow_duplicate support;
   Dash >= 2.x supports both). Report the version.
3. Read dashboard.py lines 770-1300 (render functions), 1650-1700 (layout
   stores and interval), and the tick callback near line 2763-2840, so your
   edits anchor to real code, not guesses.

---

## 1. Files to create / modify (complete list)

Create:

- assets/canvas-clientside.js   (new, ~200 lines)
- tests/test_canvas.py          (new test file)
- docs/notes optional: none

Modify:

- dashboard.py                  (add render functions, stores, layout hooks,
                                 3 new callbacks, additive Outputs on the
                                 existing tick callback)
- assets/style.css              (append a clearly marked canvas section)

Nothing else.

---

## 2. dashboard.py changes (in this order)

### 2.1 Constants block (insert after AGENT_STAGES-adjacent constants or near
the existing render-function section, around line 700-770)

Add:

    CANVAS_STAGES = [
        ("upload", "Upload", "IO"),
        ("parse", "Parse", "STEP"),
        ("rules", "Rules", "STEP"),
        ("agent_citation", "Citation Agent", "LLM"),
        ("agent_apa", "APA Agent", "LLM"),
        ("agent_sme", "SME Agent", "LLM"),
        ("summary", "Summary", "STEP"),
    ]

    CANVAS_NODE_W = 220
    CANVAS_NODE_H = 96
    CANVAS_DEFAULT_LAYOUT = {
        "positions": {
            "upload": [60, 332], "parse": [360, 332], "rules": [660, 332],
            "agent_citation": [660, 80], "agent_apa": [660, 332],
            "agent_sme": [660, 584], "summary": [940, 332],
        },
        "zoom": 1.0, "pan": [0, 0],
    }

    CANVAS_EDGES = [
        ("upload", "parse"), ("parse", "rules"),
        ("rules", "agent_citation"), ("rules", "agent_apa"),
        ("rules", "agent_sme"),
        ("agent_citation", "summary"), ("agent_apa", "summary"),
        ("agent_sme", "summary"),
    ]

Add the stage-id -> prompts.json key mapping (verify each against
src/prompts.py normalize_stage_name behavior in step 0.3 before finalizing;
write the mapping as an explicit dict regardless):

    STAGE_TO_PROMPTS_KEY = {
        "upload": None,                      # no LLM config
        "parse": "s1_extract",
        "rules": "s2_cross_section",
        "agent_citation": "s3_citations",
        "agent_apa": "s4_apa",
        "agent_sme": "s5_sme",
        "summary": "s6_report",
    }

IMPORTANT: keys s4_apa / s5_sme / s6_report must be verified against the
actual keys in configs/prompts.json (the file uses s1_extract..s7_report
style keys). Read configs/prompts.json top-level stage keys and correct the
dict to the real names. If a pipeline stage has no prompts.json entry, map
it to None and the inspector renders "No prompt configuration for this
stage." Decision-complete rule: the dict must contain exactly 7 entries
whose values are either None or real keys present in the file at save time.

### 2.2 Pure render functions (insert near _render_pipeline_region, after it)

- `_stage_status(states, name) -> str`: helper returning the status string
  for a stage from the states list (reuse whatever accessor
  _render_pipeline_region uses; do not invent a new one).
- `_edge_status(src_status, dst_status) -> str`: implement the mapping in
  design doc section 2.3 verbatim.
- `_bezier_path(x1, y1, x2, y2) -> str`: design doc 2.3 formula.
- `_render_node_card(stage_id, title, badge, status, model_label)` ->
  returns the HTML children for inside a foreignObject:
      html.Div(className=f"canvas-node status-{status}", tabIndex=0,
               role="button",
               **{"data-stage": stage_id},
               **{"aria-label": f"Stage {i} of 7, {title}, {badge} node,
                  status {status}. Press Enter to inspect."},
               children=[stripe div, badge div, title div, sub div])
  The sub div shows the model label for LLM nodes, else the status word.
  Status word badge pairs: RUN/OK/FAIL/WAIT/SKIP/CANCEL for
  running/done/failed/awaiting_approval/skipped/cancelled, empty for
  pending.
- `_render_canvas_svg(states)` -> html.Svg with:
  - html.G(className="canvas-edges", children=[paths from CANVAS_EDGES,
    each html.Path(id=f"canvas-edge-{a}--{b}",
    className=f"canvas-edge status-{edge_status}" + (" edge-running" if
    either endpoint running else ""), d=_bezier_path(...),
    fill="none", strokeWidth=2, computed from
    CANVAS_DEFAULT_LAYOUT positions)])
  - html.G(className="canvas-nodes", children=[per stage:
    html.ForeignObject(id=f"canvas-node-{stage_id}", x=pos[0], y=pos[1],
    width=CANVAS_NODE_W, height=CANVAS_NODE_H,
    children=_render_node_card(...))])
  - viewBox "0 0 1200 760", preserveAspectRatio="xMidYMid meet".
- `_render_canvas_region(states)` -> html.Div(id="canvas-region",
  className="mode-canvas", children=[toggle buttons, viewport div, activity
  panel, inspector div, export button + dcc.Download(id="canvas-download")]):
    - toggle: two html.Button("Canvas view"/"List view", id parts
      "canvas-toggle-canvas"/"canvas-toggle-list", aria-pressed set by
      callback, className "canvas-toggle-btn").
    - viewport: html.Div(id="canvas-viewport", className="canvas-viewport",
      children=[_render_canvas_svg(states)]).
    - zoom controls: buttons canvas-zoom-out / canvas-zoom-reset /
      canvas-zoom-in (labels "-", "Reset", "+").
    - activity: html.Div(id="canvas-activity", className="canvas-activity",
      role="log", **{"aria-live": "polite"}, children=_render_activity(states)).
- `_render_activity(states)` -> list of html.Div log lines: per stage in
  VALID_STAGES order, one line
  "HH:MM:SS  {title}: {status}" using the StageState timestamps if present
  (started_at/finished_at fields on StageState - read src/pipeline.py
  StageState to confirm the exact field names and use them; if a field does
  not exist, omit the timestamp and show status only). Cap at last 50 lines.
- `_render_inspector(stage_id)` -> inspector panel per design 2.6: title,
  version/updated_at line, model input, temperature number input,
  max_tokens number input, one dcc.Textarea per prompt key (id pattern
  "inspector-prompt-{key}"), char count div, Save button
  (id "inspector-save"), status line div (id "inspector-status").
  If stage is None or mapped key is None: explanatory empty state.

### 2.3 Layout stores (add in the main layout, next to the existing
dcc.Store block around line 1667-1677; do NOT reorder existing lines)

    dcc.Store(id="store-canvas-layout", storage_type="memory",
              data=CANVAS_DEFAULT_LAYOUT),
    dcc.Store(id="store-inspector-stage", storage_type="memory"),
    dcc.Store(id="store-prompts-cache", storage_type="memory"),

And insert `_render_canvas_region(...)` into the layout-grid: place it as a
full-width row directly ABOVE the existing pipeline-region block (so the
existing strip stays in the DOM underneath as list mode). Do not move or
rename pipeline-region.

### 2.4 Tick callback: additive Outputs (the ONLY edit to an existing callback)

Find the tick callback whose signature is
`Input("pip-progress", "n_intervals")` near line 2763-2771. Add to its
Outputs, AFTER the existing outputs (order within the list defines return
order - append at the END of the Outputs list and append at the END of the
returned tuple):

    Output("canvas-svg", "children"),
    Output("canvas-activity", "children"),

In the body, before the return, compute the same states object it already
builds for pipeline-region (reuse the local variable; do not re-query the
runner) and append:

    _render_canvas_svg(states),
    _render_activity(states),

to the returned tuple. Do not alter any existing return value. If the
function has multiple return paths (early returns), every return path must
gain the two new values - grep the function body for `return` and handle
each one.

### 2.5 New callbacks (add at the end of dashboard.py, after the last
existing callback; 3 callbacks + 2 clientside callbacks)

A. Toggle + node selection (one callback):
   Inputs: canvas-toggle-canvas n_clicks, canvas-toggle-list n_clicks,
           canvas-node-* clickData is NOT available for foreignObject
           children events - instead use a single Input on each node id.
   Implementation (decision): use seven Inputs, one per node wrapper's
   n_clicks is not possible on html.ForeignObject children; the standard
   Dash pattern is a clientside bridge. Use the clientside callback
   defined in 2.5-C to write store-inspector-stage on node click, and a
   Python callback:
     Inputs: store-inspector-stage,
             canvas-toggle-canvas n_clicks, canvas-toggle-list n_clicks
     Outputs: canvas-inspector children,
              canvas-region className,
              canvas-toggle-canvas aria-pressed... (Dash supports
              aria-* as writable props on html components in Dash 2.x;
              if the installed Dash version rejects aria-pressed as an
              Output, output to a data-attribute instead via
              **{"data-pressed"} on a wrapper span and style from CSS)
     Logic: className "mode-canvas" or "mode-list"; inspector children =
            _render_inspector(store-inspector-stage value or None).
   Prevent_initial_call=True.

B. Inspector save:
   Inputs: inspector-save n_clicks
   States: inspector model/temperature/max_tokens values, all
           inspector-prompt-* textareas (collect ids dynamically is not
           allowed in Python callbacks without pattern-matching callbacks -
           DECISION: use pattern-matching callback Input/State with
           {"type": "inspector-prompt", "key": ALL} for textareas, and
           fixed ids for model/temperature/max_tokens:
           inspector-model, inspector-temp, inspector-max-tokens),
           store-inspector-stage, store-pipeline.
   Logic:
     1. If any stage status in store-pipeline is "running" or the run is
        active (use the SAME active-run condition the existing Cancel
        callback uses - read it and copy the check): return status line
        "Blocked: a run is in progress. Prompts are locked until the run
        finishes or is cancelled." and dash.no_update for everything else.
     2. Validate: temperature float in [0, 2], max_tokens int in [1,
        32000], every prompt textarea non-empty. On violation return the
        message in inspector-status, no write.
     3. Load configs/prompts.json with json.load; locate stage via
        STAGE_TO_PROMPTS_KEY[stage]; update model/temperature/max_tokens
        and prompts dict; version += 1; updated_at = UTC ISO
        (datetime.now(timezone.utc).isoformat()).
     4. Write atomically: json.dump(..., ensure_ascii=True, indent=2) to
        configs/prompts.json.tmp then os.replace to configs/prompts.json.
     5. Re-read the file via src/prompts.py find_stage_config to confirm
        it parses; then return updated _render_inspector(stage) and status
        "Saved. Version {n}." Also update store-prompts-cache via a
        fourth Output.
   prevent_initial_call=True.

C. Export:
   Inputs: canvas-export-btn n_clicks
   States: store-canvas-layout, store-prompts-cache
   Outputs: canvas-download data
   Build the JSON per design 2.8 (read configs/prompts.json fresh from
   disk for stages; edges from CANVAS_EDGES; layout from the store).
   dcc.send_string(json.dumps(payload, ensure_ascii=True, indent=2),
   "asksage-workflow-{timestamp}.json"). prevent_initial_call=True.

D. Clientside callbacks (put ALL of them in assets/canvas-clientside.js
   using window.dash_clientside, NO dcc.ClientsideComponent needed):

   1. Node click -> store: delegate click and keydown (Enter/Space) on
      #canvas-svg, find closest [data-stage], set
      store-inspector-stage. Escape sets it to null (closes inspector).
   2. Arrow-key roving focus: keydown on #canvas-svg; ArrowRight/Down ->
      next node in VALID_STAGES order, ArrowLeft/Up -> previous; call
      .focus() on the node wrapper. preventDefault.
   3. Pan/zoom/drag: pointerdown on #canvas-viewport background = pan
      (update pan array); wheel with ctrl OR plain wheel on viewport =
      zoom (0.4 to 2.0, zoom toward cursor); pointerdown on a
      .canvas-node = node drag (pointermove updates the node's
      transform and redraws affected edge d attributes from
      CANVAS geometry embedded as data attributes: each path carries
      data-src/data-dst, and node groups carry data-stage plus the
      current x/y in data-x/data-y so JS can recompute beziers without
      any knowledge of card sizes beyond constants it reads from the
      DOM getBoundingClientRect of the foreignObject... DECISION: embed
      CANVAS_NODE_W/H as data-w/data-h attributes on each foreignObject
      from Python so the JS math is self-contained).
      Debounce 150ms and write store-canvas-layout
      (Output("store-canvas-layout", "data")). Zoom/reset buttons
      adjust zoom by 0.1 steps / reset to defaults through the same
      store write.
   4. Layout re-apply: subscribe via MutationObserver on #canvas-svg
      childList; on mutation, read store-canvas-layout
      (Input("store-canvas-layout", "data")) in a clientside callback
      that returns a dummy Output (use an Output on
      "canvas-viewport", "data-last-layout" - html.Div accepts
      arbitrary data-* via **kwargs; add data-last-layout="" to the
      viewport in Python) and applies stored transforms + redraws all
      edge paths. This keeps server re-renders (the 1s tick) from
      wiping user positions.

### 2.6 Preserve the 16 existing callbacks and /health: exact rules

- You may ADD Outputs to the single tick callback (section 2.4). You may
  not change any existing Input/Output/State element, order, or body logic
  of any of the 16.
- New callback ids share no Output with any existing callback Output
  (verify by grepping `Output(` and diffing the id sets before/after).
- allow_duplicate: none of your new Outputs need allow_duplicate because
  none of the ids collide. Do not add allow_duplicate anywhere.
- suppress_callback_exceptions is already True; leave it.
- /health lives in app.py; you do not open app.py. After changes, run the
  server and confirm GET /health returns 200 and GET / returns 200.

---

## 3. assets/canvas-clientside.js skeleton (required structure)

    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.canvas = {
        nodeInteract: function(...) { ... },   // click/keyboard -> inspector store
        rovingFocus: function(...) { ... },
        panZoomDrag: function(...) { ... },    // returns layout data
        applyLayout: function(layout) { ... }, // transforms + edge redraw
    };

Register with app.clientside_callback in dashboard.py (four calls,
getPatternClass not needed):

    app.clientside_callback(
        "canvas.nodeInteract",
        Output("store-inspector-stage", "data"),
        Input("canvas-svg", "n_clicks"), Input("canvas-svg", "n_keydown"),
        State("store-inspector-stage", "data"))

(and analogous for the others; keydown/n_keydown exists on html
components in Dash 2.x - if not available on html.Svg, wrap the svg in a
div and bind Inputs to that div). All constants the JS needs (node size,
bezier formula) come from data-* attributes; no duplication of Python
constants in JS beyond the bezier control-point formula which is written
inline once.

Event listeners attach once (guard with a data-bound flag on the element)
because Dash re-renders children: bind listeners on #canvas-viewport
(which is NOT re-rendered; only #canvas-svg children are), using event
delegation for nodes and edges.

---

## 4. assets/style.css additions (append at end, one marked section)

Append a block starting with the comment:

    /* ==== G3: Agent Builder canvas (Goal 3) ==== */

Required classes (implement per G3-R2-design.md sections 2 and 3):

- .canvas-viewport (height 480px desktop / 380px below 900px, overflow
  hidden, background --paper, dot grid, position relative, cursor grab,
  cursor grabbing while panning)
- .canvas-node (surface card, hairline border, radius var(--radius),
  shadow-card, stripe via ::before 4px left bar; status- modifier classes:
  status-running border --accent + .canvas-node-progress 3px bottom bar;
  status-done border-left stripe --ok; status-failed --err;
  status-awaiting-approval --warn; focus-visible outline 2px --accent
  offset 2px)
- .canvas-node-badge (pill 999px, 10px uppercase letterspaced)
- .canvas-node-title (Source Serif 4 15px --ink), .canvas-node-sub
  (Public Sans 12px --ink-muted)
- .canvas-edge (stroke colors per status class; .edge-running dasharray
  8 6 + animation edge-flow 0.9s linear infinite; keyframes defined once)
- .canvas-toggle-btn, .canvas-zoom-btn (44px min height/width, surface,
  hairline border, radius --radius)
- .canvas-activity (max-height 200px, overflow-y auto, monospace 12px
  lines, hairline top border)
- .canvas-inspector (right panel 380px on wide, full-width below 900px,
  surface, hairline border-left; textarea font monospace, min-height
  200px, resize vertical)
- @media (max-width: 559px): .mode-canvas { display: none; }
  .canvas-toggle-btn[aria-pressed="true"] for the List button hidden too,
  so only the strip shows. Also hide zoom controls in that media query.
- @media (prefers-reduced-motion: reduce): disable edge-flow animation
  and the progress bar animation.
- NO gradients (the dot grid uses radial-gradient purely as a repeating
  1px dot pattern: background-image: radial-gradient(var(--hairline) 1px,
  transparent 1px); background-size: 24px 24px; - this is the single
  sanctioned use; if audit rejects, switch to a repeating-linear hairline
  grid).
- NO emoji anywhere. ASCII only.

---

## 5. tests/test_canvas.py (new)

Pure-function tests only (no server start):

1. test_edge_status_map: each branch of _edge_status returns the expected
   status string (cover failed > done > running > warn > idle priority).
2. test_bezier_path_format: output starts with "M", contains "C", is
   space-separated numbers, endpoints match inputs.
3. test_default_layout_completeness: CANVAS_DEFAULT_LAYOUT positions has
   exactly the 7 VALID_STAGES keys.
4. test_edges_reference_valid_stages: every node in CANVAS_EDGES is in
   VALID_STAGES; edges connect in a way consistent with VALID_STAGES
   order (from-index < to-index).
5. test_stage_prompt_key_mapping: every non-None value of
   STAGE_TO_PROMPTS_KEY is a real key in configs/prompts.json["stages"].
6. test_ascii_gate_assets: read assets/canvas-clientside.js and the
   appended style.css bytes and assert all(ord(b) < 128 for b in data).

Run: .venv\Scripts\python.exe -m pytest tests/test_canvas.py -q

---

## 6. Verification sequence (run in this order, record results)

1. .venv\Scripts\python.exe -m pytest test_pipeline.py test_runner.py
   test_prompts.py tests/test_canvas.py -q        (all pass)
2. Start server: .venv\Scripts\python.exe app.py (background).
   - GET /health -> 200.
   - GET / -> 200 and response contains "canvas-viewport".
3. Open http://127.0.0.1:3080 (or the port app.py prints) in a browser:
   - Canvas renders with 7 nodes, 8 edges, agents stacked in the lane.
   - Drag a node: it moves, edges follow, refresh keeps default (memory
     store); within the session, the tick (upload a small doc and run, or
     just wait) does NOT snap it back.
   - Wheel-zoom works, clamp at 0.4x/2.0x; Reset restores.
   - Click a node: inspector opens with model/temperature/max_tokens and
     the full prompt text for Parse (s1_extract).
   - Edit a prompt, Save: configs/prompts.json shows version+1 and new
     updated_at; file re-loads fine in Python.
   - Start a run (small document): running edge animates (dashes flow),
     Activity panel lines appear, node badges update each second, Save is
     disabled/blocked with the blocked message.
   - Export workflow JSON: downloads, valid JSON, contains stages, edges,
     layout.
   - Toggle List view: the ORIGINAL strip renders identically to before
     this change (compare against git stash if needed).
4. Stop the server.

---

## 7. Acceptance / audit checklist (all must be checked)

Functional:
- [ ] 16 existing callbacks untouched (grep-diff of Output/Input lists
      before vs after shows only the tick callback gained 2 appended
      Outputs and 4 new callbacks exist).
- [ ] /health 200; app starts clean; no callback errors in server log on
      page load and during a run.
- [ ] Node drag, pan, zoom, clamp, reset all work; positions survive
      server tick re-renders.
- [ ] Inspector loads real prompts.json data; Save writes atomically,
      bumps version, blocks mid-run.
- [ ] Edge animation runs only on running edges; no polling beyond the
      existing 1000ms interval; no new server load per frame.
- [ ] Export JSON valid and complete (stages, edges, layout).
- [ ] List-mode strip renders byte-identical layout structure to pre-change.
- [ ] src/pipeline.py, src/runner.py, src/prompts.py, app.py unmodified
      (git diff --stat proves it).

Design:
- [ ] Zero emoji, zero gradients (except the sanctioned dot-grid
      background pattern), one accent color usage, radius tokens only
      (--radius and the 999px pill), no em-dashes in any string.
- [ ] All colors from existing :root tokens; no new hex values in the
      appended CSS except none (assert: the canvas section contains no
      "#" hex literals).
- [ ] Fonts: Source Serif 4 titles, Public Sans everything else.
- [ ] ASCII gate: python -c check on all touched files passes:
      .venv\Scripts\python.exe -c "import sys;[sys.exit(1) if any(ord(c)>127 for c in open(p,encoding='utf-8').read()) else None for p in ['dashboard.py','assets/style.css','assets/canvas-clientside.js','tests/test_canvas.py']]"

Accessibility:
- [ ] Nodes are tab-focusable in topological order; arrows move focus;
      Enter opens inspector; Escape closes.
- [ ] Every node has a full aria-label with stage number, title, status.
- [ ] List mode available at all times via toggle and forced below 560px.
- [ ] All buttons >= 44px touch targets.
- [ ] Status conveyed by text badge + color, never color alone.
- [ ] prefers-reduced-motion disables animations.
- [ ] Inspector inputs all have labels; textarea has a char count tied
      via aria-describedby.

---

## 8. Failure protocol

- Any pre-existing test failure in step 0: stop, report, do not fix.
- Dash API mismatch (e.g. aria-pressed as Output rejected, n_keydown
  missing on html.Svg): apply the documented fallback in the relevant
  section; if no fallback is documented, choose the smallest additive
  workaround and note it in the final report under "deviations".
- Never widen scope: no refactors of existing renderers, no renaming, no
  "improvements" to files outside Section 1.
