"""Remove the canvas renderer block and canvas callbacks from dashboard.py.

Keeps the prompt inspector machinery (_prompt_store, _labeled_input,
_labeled_textarea, _render_inspector, _run_is_blocking_save,
canvas_inspector_save) which the accordion reuses. Removes:
  - the canvas renderer block (from the "Goal 3: Agent Builder canvas
    renderers" header through _render_canvas_region's body)
  - canvas constants (_CANVAS_BADGE_WORD)
  - canvas callbacks (canvas_toggle_inspector, canvas_export,
    _stage_model_label) and the clientside registrations
  - the _render_canvas_region(None) call in build_layout

Usage: python tools/remove_canvas.py
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "dashboard.py")


def read():
    with open(DB, encoding="utf-8") as f:
        return f.read()


def write(text):
    with open(DB, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def count(s, needle):
    return s.count(needle)


def delete_block(text, start, end, tag):
    """Delete from start marker (inclusive) to end marker (inclusive)."""
    i = text.find(start)
    if i < 0:
        raise SystemExit("FAIL [%s]: start not found" % tag)
    j = text.find(end, i)
    if j < 0:
        raise SystemExit("FAIL [%s]: end not found after start" % tag)
    j += len(end)
    print("ok  %s" % tag)
    return text[:i] + text[j:]


def main():
    t = read()

    # 1. Remove the whole canvas renderers section: from the section header to
    #    the end of _render_canvas_region (the next function is _render_ledger).
    start = "# --------------------------------------------------------------------------\n# Goal 3: Agent Builder canvas renderers"
    end = "def _render_canvas_region(states):"
    # find the header then the function body end: the next top-level def after
    # _render_canvas_region is _render_ledger - we locate its start and cut
    # everything before it.
    i = t.find(start)
    if i < 0:
        raise SystemExit("FAIL: canvas renderers header not found")
    j = t.find("def _render_ledger(", i)
    if j < 0:
        raise SystemExit("FAIL: _render_ledger not found")
    print("ok  remove canvas renderers block")
    t = t[:i] + t[j:]

    # 2. Remove canvas constants _CANVAS_BADGE_WORD.
    kw_start = "#: Status word shown on the canvas node badge. Empty for pending."
    i = t.find(kw_start)
    if i < 0:
        raise SystemExit("FAIL: badge word comment not found")
    j = t.find("}", i) + 1
    print("ok  remove _CANVAS_BADGE_WORD")
    t = t[:i] + t[j:]

    # 3. Remove _render_canvas_region(None), from build_layout.
    i = t.find("            _render_canvas_region(None),")
    if i < 0:
        raise SystemExit("FAIL: build_layout canvas call not found")
    j = t.find("\n", i) + 1
    print("ok  remove build_layout canvas call")
    t = t[:i] + t[j:]

    # 4. Remove the canvas callbacks: canvas_toggle_inspector, canvas_export.
    #    Keep _run_is_blocking_save and canvas_inspector_save.
    cb_start = "def canvas_toggle_inspector("
    i = t.find(cb_start)
    if i < 0:
        raise SystemExit("FAIL: canvas_toggle_inspector not found")
    # includes the preceding decorator + outputs; find the @app.callback before it
    dec = t.rfind("@app.callback(", 0, i)
    i = dec if dec >= 0 else i
    j = t.find("def _run_is_blocking_save(", i)
    if j < 0:
        raise SystemExit("FAIL: _run_is_blocking_save not found")
    print("ok  remove canvas_toggle_inspector")
    t = t[:i] + t[j:]

    # 5. Remove canvas_export callback (from its @app.callback to end of body,
    #    i.e. before "# Canvas clientside callbacks").
    cb2 = t.find("def canvas_export(")
    if cb2 < 0:
        raise SystemExit("FAIL: canvas_export not found")
    dec2 = t.rfind("@app.callback(", 0, cb2)
    i = dec2 if dec2 >= 0 else cb2
    j = t.find("# Canvas clientside callbacks", i)
    if j < 0:
        raise SystemExit("FAIL: clientside comment not found")
    print("ok  remove canvas_export")
    t = t[:i] + t[j:]

    # 6. Remove the three clientside registrations block (comment + 3).
    cli_start = "# Canvas clientside callbacks"
    i = t.find(cli_start)
    if i < 0:
        raise SystemExit("FAIL: clientside comment (2nd) not found")
    j = t.find("# --------------------------------------------------------------------------\n# Entry point", i)
    if j < 0:
        # fallback: end of file
        j = len(t)
    print("ok  remove clientside registrations")
    t = t[:i] + t[j:]

    write(t)
    print("CANVAS REMOVED")


if __name__ == "__main__":
    main()