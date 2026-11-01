"""Postmortem document generation from structured incident data."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Incident:
    """Structured input for a postmortem."""

    title: str
    severity: str
    started: str
    detected: str
    resolved: str
    services: tuple[str, ...]
    summary: str
    impact: str
    root_cause: str
    timeline: tuple[tuple[str, str], ...] = ()
    action_items: tuple[str, ...] = ()


def render_postmortem(incident: Incident) -> str:
    """Render an incident as a Markdown postmortem."""
    lines = [
        f"# Postmortem: {incident.title}",
        "",
        f"- **Severity:** {incident.severity}",
        f"- **Started:** {incident.started}",
        f"- **Detected:** {incident.detected}",
        f"- **Resolved:** {incident.resolved}",
        f"- **Services:** {', '.join(incident.services) or 'n/a'}",
        "",
        "## Summary",
        "",
        incident.summary,
        "",
        "## Impact",
        "",
        incident.impact,
        "",
        "## Root cause",
        "",
        incident.root_cause,
        "",
        "## Timeline",
        "",
    ]
    if incident.timeline:
        lines += [f"- **{when}** - {what}" for when, what in incident.timeline]
    else:
        lines.append("- (no timeline entries recorded)")
    lines += ["", "## Action items", ""]
    if incident.action_items:
        lines += [f"- [ ] {item}" for item in incident.action_items]
    else:
        lines.append("- [ ] (no action items recorded)")
    lines.append("")
    return "\n".join(lines)
