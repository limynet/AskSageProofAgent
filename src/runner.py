"""
Background review runner for the AskSage Proof Agent (7-stage engine).

This module owns the seven-stage review pipeline (the proven "Pubs Review
Agent v3" workflow) and runs it on a daemon thread so the dashboard stays
responsive. It is the only place that knows about both the LLM layer and the
pipeline state machine.

Design points:

  * Sequential stages. The runner drives ``pub_pipeline`` stage by stage in
    canonical order (S1 Extract, S2 Cross-Section, then the gated review
    stages S3/S4/S5, then S6 Dedup, S7 Report), updating progress and the
    pipeline state between stages. Maple's 131K context means whole-document
    calls, so there is no chunked review loop.
  * Gate semantics. Only stages the operator selects (a subset of
    ``GATED_STAGES``) run; unselected gated stages are marked "skipped".
    Dedup and Report run automatically once at least one gated stage has
    completed.
  * Cancellation keeps partial results. A cancel request stops the run at
    the next stage boundary; the findings from stages already completed are
    kept and the current stage is marked "cancelled".
  * Failure isolation. An exception raised by a stage marks that stage
    "failed" with the error text in the stage detail and stops the run.

All shared mutable state (progress dict and result dict) is guarded by one
module-level lock, and every read returns a copy.

All strings in this module are English and ASCII only (no emoji).
"""

import threading
from typing import Dict, List, Optional, Sequence, Tuple

from pipeline import AGENT_STAGES, PipelineState

#: The three gated LLM review stages, in execution order.
GATED_STAGES: Tuple[str, ...] = tuple(AGENT_STAGES)

#: The stages that always run (pre-gate extraction and analysis).
PRE_GATE_STAGES: Tuple[str, ...] = ("s1_extract", "s2_cross_section")

#: The stages that run automatically once a gated stage has completed.
POST_GATE_STAGES: Tuple[str, ...] = ("s6_dedup", "s7_report")

#: Compatibility mapping from the legacy persona names to the new stage keys,
#: so callers that still talk about "citation/apa/sme" keep working.
PERSONA_STAGES: Dict[str, str] = {
    "citation": "s3_citations",
    "apa": "s4_sme",
    "sme": "s5_copyedit",
}

#: Default selection = all three gated review stages.
DEFAULT_GATED: Tuple[str, ...] = tuple(GATED_STAGES)

#: Guards the progress dict and the result dict. Reentrant because start()
#: holds the lock while computing the plan.
_LOCK = threading.RLock()

#: Seconds a caller should wait for a run to settle before giving up.
DEFAULT_JOIN_TIMEOUT = 10.0


def _resolve_selection(selected):
    """Normalize a stage/persona selection into ordered gated stage keys.

    Accepts either the legacy persona names ("citation", "apa", "sme") or the
    new stage keys ("s3_citations", ...). Returns a de-duplicated list in
    GATED_STAGES order. Unknown names are dropped. Raises ValueError when
    nothing usable remains.
    """
    if selected is None:
        return list(DEFAULT_GATED)
    requested = []
    for item in selected or []:
        if not isinstance(item, str):
            continue
        key = PERSONA_STAGES.get(item, item)
        if key in GATED_STAGES and key not in requested:
            requested.append(key)
    if not requested:
        raise ValueError(
            "No gated review stages selected. Valid: {0}".format(", ".join(GATED_STAGES))
        )
    # Order by GATED_STAGES canonical order.
    return [s for s in GATED_STAGES if s in requested]


def _empty_progress() -> Dict[str, object]:
    """Return a fresh progress dict in its idle state."""
    return {
        "stage": "",
        "chunk_index": 0,
        "chunk_total": 0,
        "findings_so_far": 0,
        "cancel_requested": False,
        "message": "idle",
    }


class ReviewRun:
    """Run the seven-stage review pipeline on a daemon thread.

    Args:
        llm_client: Any object exposing
            ``chat_completion(messages, temperature, max_tokens)``. A real
            LLMClient works, and so does a duck-typed test double.
        selected: Gated stages to run (persona names or stage keys). Defaults
            to all three gated stages.
        pipeline: Optional PipelineState to drive. When omitted a fresh one
            is created; injecting one lets a caller (or a test) assert the
            resulting stage statuses.
    """

    def __init__(
        self,
        llm_client,
        selected: Optional[Sequence[str]] = None,
        pipeline: Optional[PipelineState] = None,
        client_factory=None,
    ) -> None:
        self.llm_client = llm_client
        self.client_factory = client_factory
        self.pipeline = pipeline if pipeline is not None else PipelineState()
        self.selected: List[str] = _resolve_selection(selected)

        # Import lazily so the runner module imports even if the pipeline
        # engine is unavailable; callers get a sane error at start() instead.
        self._pub_pipeline = None

        self.progress: Dict[str, object] = _empty_progress()
        self._results: Dict[str, Dict[str, List[object]]] = {}
        self._report_text: str = ""
        self._thread: Optional[threading.Thread] = None
        self._finished = threading.Event()
        self._finished.set()
        self._cancel_requested = False

    # -- helpers ----------------------------------------------------------

    def _build_engine(self):
        """Lazily import and build the PubPipeline engine wrapper."""
        from pub_pipeline import ProviderAdapter, PubPipeline

        self._pub_pipeline = PubPipeline(
            ProviderAdapter(self.llm_client),
            client_factory=self.client_factory,
        )
        return self._pub_pipeline

    def _set_progress(self, **fields) -> None:
        """Update the shared progress dict under the module lock."""
        with _LOCK:
            self.progress.update(fields)

    def progress_snapshot(self) -> Dict[str, object]:
        """Return a consistent copy of the live progress dict."""
        with _LOCK:
            return dict(self.progress)

    # -- lifecycle --------------------------------------------------------

    def start(self, text: str, selected: Optional[Sequence[str]] = None) -> bool:
        """Start the run on a daemon thread and return immediately.

        Idempotent: calling it while a run is in flight is a no-op returning
        False.

        Args:
            text: The manuscript text to review.
            selected: Optional gated selection override for this run.

        Returns:
            True when a new run was started, False when one was already
            running.
        """
        if self.is_running():
            return False

        if selected:
            self.selected = _resolve_selection(selected)

        with _LOCK:
            self._results = {}
            self._cancel_requested = False
            self.progress = _empty_progress()
            self.progress["message"] = "starting"

        self._finished.clear()
        self._thread = threading.Thread(
            target=self._work,
            args=(text,),
            name="asksage-seven-stage-run",
            daemon=True,
        )
        self._thread.start()
        return True

    def cancel(self) -> None:
        """Request cancellation of the running pass.

        The worker stops at the next stage boundary; findings from completed
        stages are kept. Calling cancel() when nothing is running is
        harmless.
        """
        with _LOCK:
            self._cancel_requested = True
            self.progress["cancel_requested"] = True
            self.progress["message"] = "cancel requested"

    def is_running(self) -> bool:
        """Return True while the worker thread is executing."""
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def join(self, timeout: float = DEFAULT_JOIN_TIMEOUT) -> bool:
        """Wait for the worker thread to settle."""
        thread = self._thread
        if thread is None:
            return True
        try:
            thread.join(timeout)
        except Exception:
            return not thread.is_alive()
        return not thread.is_alive()

    # -- results ----------------------------------------------------------

    def result(self) -> Dict[str, Dict[str, List[object]]]:
        """Return the findings and notes accumulated so far.

        Keyed by pipeline stage name; each value has "findings" and "notes"
        lists. Shallow copy, safe to read while the worker keeps running.
        """
        with _LOCK:
            return {
                stage: {
                    "findings": list(payload.get("findings", [])),
                    "notes": list(payload.get("notes", [])),
                }
                for stage, payload in self._results.items()
            }

    def findings_count(self) -> int:
        """Return the number of findings accumulated so far."""
        total = 0
        with _LOCK:
            for payload in self._results.values():
                total += len(payload.get("findings", []))
        return total

    def report_text(self) -> str:
        """Return the final editorial report text (stage 7), or empty."""
        with _LOCK:
            return self._report_text

    # -- worker -----------------------------------------------------------

    #: Mapping from a gated stage to the ctx key holding its raw findings.
    _ANALYSIS_FINDINGS_KEYS = {
        "s3_citations": "citations_apa_analysis_findings",
        "s4_sme": "sme_analysis_findings",
        "s5_copyedit": "copyedit_analysis_findings",
    }

    def _work(self, text: str) -> None:
        """Execute the seven-stage pipeline on the daemon worker thread."""
        cancelled = False
        failed = False
        try:
            engine = self._build_engine()
            if engine is None:
                self._set_progress(message="engine unavailable")
                return

            ctx = {"manuscript_text": text or ""}

            run_order = (
                list(PRE_GATE_STAGES)
                + list(self.selected)
                + list(POST_GATE_STAGES)
            )

            for stage in run_order:
                if cancelled or failed:
                    break
                if self._cancel_requested_now():
                    self.pipeline.set_status(stage, "cancelled", "cancelled before start")
                    cancelled = True
                    break

                self.pipeline.set_status(stage, "running", "stage {0}".format(stage))
                self._set_progress(
                    stage=stage,
                    chunk_index=0,
                    chunk_total=1,
                    message="running {0}".format(stage),
                )

                try:
                    runner_name = engine.STAGE_RUNNERS[stage]
                    runner = getattr(engine, runner_name)
                    runner(ctx)
                except Exception as exc:
                    self.pipeline.set_status(stage, "failed", str(exc))
                    self._append_note(stage, "stage failed: {0}".format(exc))
                    failed = True
                    break

                # Normalize the stage findings into the shared app schema.
                raw_key = self._ANALYSIS_FINDINGS_KEYS.get(stage)
                app_findings = []
                if raw_key:
                    try:
                        from pub_pipeline import findings_to_app

                        raw = ctx.get(raw_key, []) or []
                        app_findings = findings_to_app(raw)
                    except Exception:  # noqa: BLE001 - findings stay empty on error
                        app_findings = []

                if stage == "s7_report":
                    with _LOCK:
                        self._report_text = ctx.get("final_report", "") or ""

                self._store(stage, app_findings, [])

                self.pipeline.set_status(
                    stage,
                    "done",
                    "{0} finding(s)".format(len(app_findings)),
                )
                self.pipeline.set_count(stage, len(app_findings))
                self._set_progress(
                    stage=stage,
                    chunk_index=1,
                    chunk_total=1,
                    findings_so_far=self.findings_count(),
                    message="finished {0}".format(stage),
                )

            # Mark unselected gated stages as skipped so the strip does not
            # leave them silently pending after the run settles.
            for gated in GATED_STAGES:
                current = self.pipeline.get(gated).status
                if current == "pending":
                    self.pipeline.set_status(gated, "skipped", "deselected by the operator")

        except Exception as exc:  # pragma: no cover - defensive outer guard
            self._set_progress(message="runner error: {0}".format(exc))
        finally:
            with _LOCK:
                self.progress["message"] = (
                    "cancelled" if cancelled else ("failed" if failed else "finished")
                )
                self.progress["findings_so_far"] = self.findings_count()
            self._finished.set()

    def _cancel_requested_now(self) -> bool:
        """Return True when cancellation has been requested."""
        with _LOCK:
            return bool(self._cancel_requested)

    def _store(self, stage_name: str, findings: List[object], notes: List[str]) -> None:
        """Publish the accumulated findings and notes for one stage."""
        with _LOCK:
            self._results[stage_name] = {
                "findings": list(findings),
                "notes": list(notes),
            }

    def _append_note(self, stage_name: str, note: str) -> None:
        """Append a single note to a stage's note list."""
        with _LOCK:
            payload = self._results.setdefault(
                stage_name, {"findings": [], "notes": []}
            )
            payload["notes"].append(note)


def run_agents(
    llm_client,
    text: str,
    selected: Optional[Sequence[str]] = None,
    pipeline: Optional[PipelineState] = None,
    timeout: float = DEFAULT_JOIN_TIMEOUT,
) -> Tuple[Dict[str, Dict[str, List[object]]], PipelineState]:
    """Convenience helper: run the pipeline and wait for the result."""
    run = ReviewRun(llm_client, selected=selected, pipeline=pipeline)
    run.start(text, selected=selected)
    run.join(timeout)
    return run.result(), run.pipeline


__all__ = [
    "ReviewRun",
    "run_agents",
    "PERSONA_STAGES",
    "DEFAULT_GATED",
    "PRE_GATE_STAGES",
    "POST_GATE_STAGES",
    "AGENT_STAGES",
]