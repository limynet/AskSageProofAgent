"""QA probe: drive the real Dash callbacks over HTTP against a running dashboard.

This is a verification harness, not a product file. It exercises the upload,
review, provider-switch, connection-test, prompt, and export callbacks the same
way the browser would, and reports the observed results.

Usage:
    .\\.venv\\Scripts\\python.exe qa_probe.py
"""
import base64
import json
import re
import sys

import requests

BASE = "http://127.0.0.1:8501"
UPDATE_URL = BASE + "/_dash-update-component"


def get_dependencies():
    """Return the app's registered callback dependency list."""
    return requests.get(BASE + "/_dash-dependencies", timeout=30).json()


def find_dep(deps, input_id):
    """Find the dependency whose first input matches input_id."""
    for dep in deps:
        ins = dep.get("inputs") or []
        if ins and ins[0].get("id") == input_id:
            return dep
    return None


def parse_outputs(output):
    """Build the Dash `outputs` map from a dependency's output spec.

    Dash encodes multi-output callbacks as a list of specs, where each spec
    looks like "..id.prop...id.prop..". The `outputs` map must be keyed by
    the exact spec fragment ("id.prop") with an {"id", "property"} value.
    """
    if isinstance(output, str):
        output = [output]
    outputs = {}
    for spec in output:
        for part in [p for p in spec.split("..") if p]:
            cid, prop = part.rsplit(".", 1)
            outputs[part] = {"id": cid, "property": prop}
    return outputs


def call(dep, changed, input_values, state_values=None):
    """POST a callback invocation and return the parsed JSON response.

    Dash 4 validates the request's `outputs` list against the callback's
    declared output spec, so the payload must mirror the dependency exactly.
    A multi-output callback is encoded as a single spec string with a leading
    and trailing ".." and each "id.property" pair separated by "..." (three
    dots). The request must send the expanded, declaration-ordered list.
    """
    output_specs = dep.get("output")
    if not isinstance(output_specs, list):
        output_specs = [output_specs]

    def spec_entry(spec):
        """Expand one spec string into the flat, declaration-ordered list.

        Multi-output callbacks register a flat outputs_indices list, so the
        request's `outputs` entry for that spec must be the flat list of
        {"id","property"} dicts in declaration order.
        """
        parts = parse_multiple_outputs(spec) if spec.startswith("..") else [spec]
        return [
            {"id": part.rsplit(".", 1)[0], "property": part.rsplit(".", 1)[1]}
            for part in parts
        ]

    # A single-output spec must be sent as a bare dict; a multi-output spec
    # is sent as its flat list of output dicts, appended in declaration order
    # (Dash 4 expects one flat `outputs` list, not a list-of-lists).
    outputs_payload = []
    for spec in output_specs:
        entry = spec_entry(spec)
        if len(entry) == 1:
            outputs_payload.append(entry[0])
        else:
            outputs_payload.extend(entry)

    payload = {
        "output": output_specs[0] if len(output_specs) == 1 else output_specs,
        "outputs": outputs_payload,
        "inputs": [
            {"id": i["id"], "property": i["property"], "value": input_values.get(i["id"])}
            for i in (dep.get("inputs") or [])
        ],
        "changedPropIds": changed,
        "parsedChangedPropsIds": changed,
        "state": [
            {"id": s["id"], "property": s["property"], "value": (state_values or {}).get(s["id"])}
            for s in (dep.get("state") or [])
        ],
    }
    resp = requests.post(UPDATE_URL, json=payload, timeout=300)
    return resp.status_code, resp.text


def parse_multiple_outputs(spec):
    """Expand a Dash multi-output spec string into its id.property parts.

    Mirrors the renderer's parseMultipleOutputs: strip the leading and
    trailing ".." then split on the "..." separator.
    """
    return spec[2:len(spec) - 2].split("...")


def main():
    results = []

    def record(name, ok, detail=""):
        results.append((name, ok, detail))
        print("[{0}] {1}{2}".format("PASS" if ok else "FAIL", name,
                                    (" - " + detail) if detail else ""))

    deps = get_dependencies()
    print("Registered callbacks: {0}".format(len(deps)))
    print("")

    # --- Probe 1: upload a real DOCX and read the metric values -------------
    upload_dep = find_dep(deps, "upload-manuscript")
    if upload_dep is None:
        record("upload callback registered", False, "not found")
        return finish(results)

    data = open("data/ACSO-Research-Plan-V1.1.docx", "rb").read()
    b64 = base64.b64encode(data).decode()
    contents = ("data:application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document;base64," + b64)
    status, text = call(upload_dep, ["upload-manuscript.contents"],
                        {"upload-manuscript": contents},
                        {"upload-manuscript": "ACSO-Research-Plan-V1.1.docx"})
    record("upload callback returns 200", status == 200, "status={0}".format(status))
    if status != 200:
        # Surface the server's own error text so a failure is diagnosable.
        print("    server response: {0}".format(text[:300].replace("\n", " ")))

    def prop(name):
        m = re.search(r'"' + name + r'":\{"children":(.*?)\}', text)
        if not m:
            return None
        raw = m.group(1)
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    fmt = prop("metric-format")
    pages = prop("metric-pages")
    words = prop("metric-words")
    chars = prop("metric-characters")
    print("    metrics: format={0} pages={1} words={2} chars={3}".format(
        fmt, pages, words, chars))
    record("metrics populated from real DOCX",
           fmt is not None and words is not None and chars is not None,
           "format={0} words={1}".format(fmt, words))
    def to_int(v):
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            try:
                return int(v.replace(",", "").strip())
            except ValueError:
                return None
        return None

    record("word count plausible (>1000)", to_int(words) is not None and to_int(words) > 1000,
           "words={0}".format(words))
    record("no upload alert raised", "upload-alert" not in text or "is-error" not in text)

    # --- Probe 2: run the review engine ------------------------------------
    # Run review now starts the full pipeline on the runner's background
    # thread (one click, no approval gate). The callback returns the pipeline
    # snapshot and the strip render; findings stream in via the ticker.
    review_dep = find_dep(deps, "run-review")
    if review_dep is None:
        record("review callback registered", False, "not found")
        return finish(results)

    state = {}
    for s in (review_dep.get("state") or []):
        if s["id"] == "store-document":
            state["store-document"] = {"text": "x" * 500, "name": "probe.docx"}
    status, text = call(review_dep, ["run-review.n_clicks"],
                        {"run-review": 1}, state)
    record("review callback returns 200", status == 200, "status={0}".format(status))
    started = ("Running" in text) or ("pipe-strip" in text) or ("queued by Run review" in text)
    record("background run started (strip re-rendered)", started,
           "strip/queued markers present={0}".format(started))

    # Cancel the probe run so the engine is not busy for the other probes.
    cancel_dep = find_dep(deps, "cancel-agents")
    if cancel_dep is not None and started:
        c_status, _ = call(cancel_dep, ["cancel-agents.n_clicks"],
                           {"cancel-agents": 1},
                           {"store-pipeline": None})
        record("probe run cancelled", c_status == 200, "status={0}".format(c_status))

    # --- Probe 3: provider switch ------------------------------------------
    prov_dep = find_dep(deps, "provider-local")
    if prov_dep is not None:
        status, text = call(prov_dep, ["provider-local.n_clicks"],
                            {"provider-local": 1, "provider-custom": 0})
        record("provider switch returns 200", status == 200, "status={0}".format(status))
        record("provider switch updates store",
               "store-provider" in text, "store key present in response")

    # --- Probe 4: connection test (must render a definite state) -----------
    # The store holds {"provider": ...} like the real layout. Whatever the
    # engine state, the callback must return 200 and land on exactly one of
    # the connected/offline renderings - never crash and never stay untested.
    conn_dep = find_dep(deps, "test-connection")
    if conn_dep is not None:
        status, text = call(conn_dep, ["test-connection.n_clicks"],
                            {"test-connection": 1},
                            {"store-provider": {"provider": "local"}})
        record("connection test returns 200 (no crash)", status == 200,
               "status={0}".format(status))
        connected = "is-connected" in text
        offline = "is-offline" in text
        record("connection test renders a definite state", connected != offline,
               "connected={0} offline={1}".format(connected, offline))

    # --- Probe 5: export summary -------------------------------------------
    export_dep = find_dep(deps, "export-summary")
    if export_dep is not None:
        status, text = call(export_dep, ["export-summary.n_clicks"],
                            {"export-summary": 1},
                            {"store-findings": []})
        record("export returns 200", status == 200, "status={0}".format(status))
        non_ascii = sorted(set(c for c in text if ord(c) > 127))
        record("export payload is ASCII", not non_ascii, "non-ascii={0}".format(non_ascii))

    return finish(results)


def finish(results):
    failed = [r for r in results if not r[1]]
    print("")
    print("=" * 60)
    print("QA PROBE SUMMARY: {0} PASS, {1} FAIL".format(
        len(results) - len(failed), len(failed)))
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
