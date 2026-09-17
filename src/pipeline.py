"""
Pipeline state machine for the AskSage Proof Agent review workflow.

This module is a pure, dependency-free state machine. It performs no I/O,
starts no threads, and imports nothing beyond the Python standard library
(dataclasses and typing). That constraint is deliberate: the dashboard can
drive the whole seven-stage workflow from this object alone, and the
background runner in ``runner.py`` can report progress into it from a
worker thread without the state machine knowing anything about the LLM
layer.

Stage order (fixed, matching the proven "Pubs Review Agent v3" workflow):

    s1_extract -> s2_cross_section -> s3_citations -> s4_sme
    -> s5_copyedit -> s6_dedup -> s7_report

The three gated LLM review stages (``s3_citations``, ``s4_sme``,
``s5_copyedit``) are held behind human approval: they only become approvable
once the preceding stages have finished, and only while they are still
``pending``.

All strings in this module are English and ASCII only (no emoji).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

#: The seven stages in their canonical execution order.
VALID_STAGES: List[str] = [
    "s1_extract",
    "s2_cross_section",
    "s3_citations",
    "s4_sme",
    "s5_copyedit",
    "s6_dedup",
    "s7_report",
]

#: Every status a stage is allowed to hold.
VALID_STATUSES: List[str] = [
    "pending",
    "running",
    "done",
    "skipped",
    "failed",
    "cancelled",
    "awaiting_approval",
]

#: The three gated LLM review stages, in execution order.
AGENT_STAGES: List[str] = ["s3_citations", "s4_sme", "s5_copyedit"]

#: Statuses that mean a stage has stopped and will not run again on its own.
TERMINAL_STATUSES = ("done", "skipped", "failed", "cancelled")


@dataclass
class StageState:
    """Mutable state for a single pipeline stage.

    Attributes:
        name: The stage name; always one of VALID_STAGES.
        status: The current status; always one of VALID_STATUSES.
        started_at: ISO-8601 timestamp of the first pending -> running
            transition, or None while the stage has never started.
        finished_at: ISO-8601 timestamp recorded when the stage left the
            "running" status, or None while it is still running (or has
            never started).
        count: Stage-specific count. Carries the number of findings for an
            agent stage, or the number of deterministic rule hits for the
            "s2_cross_section" stage.
        detail: Free-form stage detail. Carries the model name, a skip
            reason, an error message, or a rule count summary.
    """

    name: str
    status: str = "pending"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    count: int = 0
    detail: str = ""


@dataclass
class PipelineState:
    """Ordered container of StageState objects for the seven-stage pipeline.

    The container is intentionally not thread safe by itself; callers that
    update it from a worker thread must serialize their own access (the
    runner module does this with a module-level lock).

    Attributes:
        stages: The seven StageState objects, in VALID_STAGES order.
    """

    stages: List[StageState] = field(default_factory=list)

    def __init__(self) -> None:
        """Create a fresh pipeline with every stage in the "pending" status."""
        self.stages = [StageState(name=name, status="pending") for name in VALID_STAGES]

    # -- lookups ----------------------------------------------------------

    def get(self, name: str) -> StageState:
        """Return the StageState for a stage name.

        Args:
            name: The stage name to look up.

        Returns:
            The matching StageState object (live, not a copy).

        Raises:
            ValueError: If the name is not one of VALID_STAGES.
        """
        if name not in VALID_STAGES:
            raise ValueError(
                "Unknown stage: {0}. Valid stages: {1}".format(
                    name, ", ".join(VALID_STAGES)
                )
            )
        for stage in self.stages:
            if stage.name == name:
                return stage
        # Unreachable while stages is built from VALID_STAGES, but kept so
        # the method never returns None silently.
        raise ValueError("Stage not present in this pipeline: {0}".format(name))

    def names(self) -> List[str]:
        """Return the stage names in pipeline order."""
        return [stage.name for stage in self.stages]

    # -- transitions ------------------------------------------------------

    def set_status(self, name: str, status: str, detail: str = "") -> StageState:
        """Set a stage status and maintain its timestamps.

        Timestamp rules:
            * ``started_at`` is stamped only on the first transition out of
              "pending" into "running"; a later re-run keeps the original
              start time.
            * ``finished_at`` is stamped whenever the stage leaves the
              "running" status (to done, skipped, failed, cancelled, or back
              to pending on a reset).

        Args:
            name: The stage name; must be in VALID_STAGES.
            status: The new status; must be in VALID_STATUSES.
            detail: Optional detail text (model name, skip reason, error
                message, rule count). Only written when non-empty, so a
                later transition does not silently erase an earlier reason.

        Returns:
            The updated StageState.

        Raises:
            ValueError: If name or status is not valid.
        """
        if name not in VALID_STAGES:
            raise ValueError(
                "Unknown stage: {0}. Valid stages: {1}".format(
                    name, ", ".join(VALID_STAGES)
                )
            )
        if status not in VALID_STATUSES:
            raise ValueError(
                "Unknown status: {0}. Valid statuses: {1}".format(
                    status, ", ".join(VALID_STATUSES)
                )
            )

        stage = self.get(name)
        previous = stage.status

        if status == "running" and previous == "pending" and not stage.started_at:
            stage.started_at = _now_iso()
        if previous == "running" and status != "running":
            stage.finished_at = _now_iso()
        if status == "pending":
            # A reset of a single stage clears its timing bookkeeping.
            stage.started_at = None
            stage.finished_at = None

        stage.status = status
        if detail:
            stage.detail = detail
        return stage

    def set_count(self, name: str, count: int) -> StageState:
        """Record a stage count (findings or rule hits).

        Args:
            name: The stage name; must be in VALID_STAGES.
            count: The number to store.

        Returns:
            The updated StageState.
        """
        stage = self.get(name)
        stage.count = int(count)
        return stage

    def reset(self) -> "PipelineState":
        """Return the pipeline to a fresh state (all stages pending).

        Returns:
            This same PipelineState instance, for convenient chaining.
        """
        for stage in self.stages:
            stage.status = "pending"
            stage.started_at = None
            stage.finished_at = None
            stage.count = 0
            stage.detail = ""
        return self

    # -- derived views ----------------------------------------------------

    def approvable_agents(self, rules_done: bool) -> List[str]:
        """Return the agent stages a human may approve right now.

        An agent stage is approvable only when the deterministic rules pass
        has finished (``rules_done`` is True) and the stage has not been
        started, skipped, or finished yet (its status is still "pending").

        Args:
            rules_done: True when the cross-section/rules stage
                ("s2_cross_section") has completed.

        Returns:
            A list drawn from AGENT_STAGES, in that order. Empty when the
            cross-section stage is not done or when no agent stage is pending.
        """
        if not rules_done:
            return []
        return [
            name
            for name in AGENT_STAGES
            if self.get(name).status == "pending"
        ]

    def next_action(self) -> str:
        """Return a short hint string describing what the UI should do next.

        Intended logic, evaluated in this order:
            1. "failed" - any stage is "failed"; the run needs attention.
            2. "awaiting_approval" - any stage is "awaiting_approval"; a
               human decision is blocking the pipeline.
            3. "running" - any stage is "running"; work is in flight.
            4. "idle" - the cross-section stage ("s2_cross_section") is
               "pending" or "running", so the agent stages cannot be
               offered yet.
            5. "done" - the final-report stage ("s7_report") is "done".
            6. "idle" - nothing above matched (for example everything was
               skipped or cancelled, or the run has not started).

        The order matters: a failure anywhere outranks a pending approval,
        which outranks in-flight work, so the UI never hides a problem.

        Returns:
            One of "failed", "awaiting_approval", "running", "done", "idle".
        """
        statuses = [stage.status for stage in self.stages]

        if "failed" in statuses:
            return "failed"
        if "awaiting_approval" in statuses:
            return "awaiting_approval"
        if "running" in statuses:
            return "running"
        if self.get("s7_report").status == "done":
            return "done"
        if self.get("s2_cross_section").status in ("pending", "running"):
            return "idle"
        return "idle"

    def summary_status(self) -> str:
        """Return the effective status of the final-report stage.

        The final-report stage ("s7_report") is only meaningful when there is
        something to summarize. It reports "done" only when at least one of
        the cross-section stage or any agent stage actually completed
        ("done"); otherwise the raw status of the report stage is returned
        unchanged (for example "pending" when nothing has run, or "cancelled"
        when the run was cancelled before any pass produced findings).

        Returns:
            "done" when the report is done and at least one upstream stage
            completed, else the raw report stage status.
        """
        summary = self.get("s7_report")
        if summary.status != "done":
            return summary.status

        completed_upstream = self.get("s2_cross_section").status == "done"
        if not completed_upstream:
            for name in AGENT_STAGES:
                if self.get(name).status == "done":
                    completed_upstream = True
                    break

        if completed_upstream:
            return "done"
        return summary.status

    # -- serialization ----------------------------------------------------

    def to_dict(self) -> Dict[str, object]:
        """Return a JSON-serializable snapshot of the pipeline.

        Returns:
            A dict with a "stages" list (one dict per stage, in pipeline
            order) and a "next_action" hint string.
        """
        return {
            "stages": [
                {
                    "name": stage.name,
                    "status": stage.status,
                    "started_at": stage.started_at,
                    "finished_at": stage.finished_at,
                    "count": stage.count,
                    "detail": stage.detail,
                }
                for stage in self.stages
            ],
            "next_action": self.next_action(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "PipelineState":
        """Rebuild a PipelineState from a to_dict() snapshot.

        Unknown stage names in the snapshot are ignored and missing stages
        are created as "pending", so a snapshot from an older build still
        loads.

        Args:
            data: A dict previously produced by to_dict().

        Returns:
            A new PipelineState.
        """
        state = cls()
        for item in (data or {}).get("stages", []) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if name not in VALID_STAGES:
                continue
            stage = state.get(name)
            status = item.get("status", "pending")
            stage.status = status if status in VALID_STATUSES else "pending"
            stage.started_at = item.get("started_at")
            stage.finished_at = item.get("finished_at")
            stage.count = int(item.get("count", 0) or 0)
            stage.detail = item.get("detail", "") or ""
        return state


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
