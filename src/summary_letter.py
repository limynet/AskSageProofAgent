"""
Summary Letter Module

Builds a Markdown summary letter from a review result produced by
run_review in review_agents.py.

ASCII only, no emoji, no em dashes (plain hyphens or restructured sentences).
"""


def build_summary_letter(manuscript_name, review_result, generated_with):
    """Build a Markdown summary letter for a manuscript review.

    Args:
        manuscript_name: Display name of the manuscript.
        review_result: The dict returned by run_review.
        generated_with: String naming the engine that produced the review,
            e.g. "Bonsai-1.7B (local)" or "Custom API".

    Returns:
        A Markdown string.
    """
    summary = review_result.get("summary", {})
    errors = summary.get("error", 0)
    warnings = summary.get("warning", 0)
    infos = summary.get("info", 0)
    total = summary.get("total", 0)

    lines = []
    lines.append("# Manuscript Review Summary")
    lines.append("")
    lines.append("**Manuscript:** {}".format(manuscript_name))
    lines.append("")

    lines.append(
        "This review found {} finding(s): {} error(s), {} warning(s), and "
        "{} info item(s). Findings are grouped below by review agent. "
        "Each finding lists a location and a suggested fix.".format(
            total, errors, warnings, infos
        )
    )
    lines.append("")

    # Group findings by agent.
    by_agent = {}
    for f in review_result.get("findings", []):
        agent = f.get("agent", "citation")
        by_agent.setdefault(agent, []).append(f)

    agent_labels = {
        "citation": "Citation Review",
        "apa": "APA Style Review",
        "sme": "Army Publication (SME) Review",
    }

    for agent in ("citation", "apa", "sme"):
        agent_findings = by_agent.get(agent, [])
        if not agent_findings:
            continue
        lines.append("## {}".format(agent_labels.get(agent, agent)))
        lines.append("")
        for idx, f in enumerate(agent_findings, start=1):
            severity = f.get("severity", "info").upper()
            location = f.get("location", "document")
            original = f.get("original_text", "")
            issue = f.get("issue", "")
            fix = f.get("suggested_fix", "")
            source = f.get("source", "")
            lines.append(
                "{}. [{}] Location: {}. {}".format(idx, severity, location, issue)
            )
            if original:
                lines.append("   Original: {}".format(original))
            if fix:
                lines.append("   Suggested fix: {}".format(fix))
            if source:
                lines.append("   Source: {}".format(source))
            lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append(
        "This review was generated with {}. It combines deterministic "
        "rule-based checks with semantic review where an LLM engine is "
        "available.".format(generated_with)
    )
    lines.append("")
    lines.append(
        "Automated findings require human verification before any changes "
        "are made to the manuscript."
    )
    lines.append("")
    return "\n".join(lines)
