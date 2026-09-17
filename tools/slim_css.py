"""Replace the canvas CSS tail with the prompt-editor styles the accordion
uses. Keeps only the reusable inspector/field/button rules and adds the new
reference-list and step-label rules. Removes all dead canvas SVG/node/edge.

Usage: python tools/slim_css.py
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(ROOT, "assets", "style.css")

KEEP_BLOCK = """/* ==== Prompt editor (per-node accordion) ==== */

.canvas-inspector {
    color: var(--ink);
}

.canvas-inspector-head {
    font-family: var(--font-serif);
    font-size: 16px;
    margin: 16px 0 4px;
}

.canvas-inspector-meta {
    font-size: 12px;
    color: var(--ink-muted);
    margin-bottom: 12px;
}

.canvas-inspector-empty {
    color: var(--ink-muted);
    padding: 16px 0;
}

.canvas-inspector-status {
    margin-top: 12px;
    font-size: 13px;
    color: var(--ink-muted);
}

.canvas-field-row {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
}

.canvas-field-row .canvas-field {
    flex: 1 1 120px;
    min-width: 0;
}

.canvas-field {
    margin-bottom: 12px;
}

.canvas-field-label {
    display: block;
    font-size: 12px;
    color: var(--ink-muted);
    margin-bottom: 4px;
}

.canvas-step-label {
    display: block;
    font-size: 13px;
    font-weight: 600;
    color: var(--ink);
    margin: 14px 0 4px;
}

.canvas-field.is-prompt {
    margin-top: 8px;
}

.canvas-inp {
    width: 100%;
    box-sizing: border-box;
    min-height: 40px;
    padding: 6px 8px;
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-radius: var(--radius);
    font-family: var(--font-sans);
    font-size: 14px;
    color: var(--ink);
}

.canvas-ta {
    width: 100%;
    box-sizing: border-box;
    min-height: 160px;
    padding: 8px;
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-radius: var(--radius);
    font-family: monospace;
    font-size: 12px;
    color: var(--ink);
    resize: vertical;
}

.canvas-char-count {
    font-size: 12px;
    color: var(--ink-muted);
    margin-bottom: 12px;
}

.canvas-save-btn {
    min-height: 44px;
    padding: 0 20px;
    background: var(--accent);
    border: 1px solid var(--accent);
    border-radius: var(--radius);
    color: var(--paper);
    font-family: var(--font-sans);
    font-size: 14px;
    cursor: pointer;
}

.canvas-save-btn:hover {
    background: var(--accent-dark);
    border-color: var(--accent-dark);
}

.canvas-refs {
    margin: 12px 0;
    padding: 10px 12px;
    background: var(--paper);
    border: 1px solid var(--hairline);
    border-radius: var(--radius);
}

.canvas-ref-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
    padding: 2px 0;
}

.canvas-ref-title {
    font-size: 13px;
    color: var(--ink);
}

.canvas-ref-muted {
    font-size: 13px;
    color: var(--ink-muted);
}

.canvas-ref-state {
    font-size: 12px;
    white-space: nowrap;
}

.canvas-ref-state.is-loaded {
    color: var(--ok);
}

.canvas-ref-state.is-notloaded {
    color: var(--warn);
}
"""


def main():
    with open(CSS, encoding="utf-8") as f:
        text = f.read()
    marker = "/* ==== G3: Agent Builder canvas (Goal 3) ==== */"
    idx = text.find(marker)
    if idx < 0:
        raise SystemExit("FAIL: canvas css marker not found")
    new_text = text[:idx].rstrip() + "\n\n" + KEEP_BLOCK.rstrip() + "\n"
    with open(CSS, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)
    print("CSS SLIMMED; new length:", len(new_text))


if __name__ == "__main__":
    main()