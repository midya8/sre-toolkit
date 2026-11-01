"""Postmortem document generation from structured incident data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


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


@dataclass(frozen=True)
class ResponseMetrics:
    """Response times computed from incident timestamps.

    ``time_to_detect`` is start to detection, ``time_to_resolve`` is
    detection to resolution, and ``total_duration`` is start to resolution.
    """

    time_to_detect: timedelta
    time_to_resolve: timedelta
    total_duration: timedelta


def _parse_timestamp(value: str) -> datetime | None:
    """Parse an incident timestamp; None when the format is unknown."""
    text = value.strip()
    if text.endswith(" UTC"):
        text = text[:-4] + "+00:00"
    elif text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def response_metrics(incident: Incident) -> ResponseMetrics | None:
    """Compute response metrics, or None when the timestamps do not allow it.

    Returns None when any timestamp is unparseable, when naive and
    timezone-aware values are mixed, or when the values are out of order
    (detection before start, or resolution before detection).
    """
    started = _parse_timestamp(incident.started)
    detected = _parse_timestamp(incident.detected)
    resolved = _parse_timestamp(incident.resolved)
    if started is None or detected is None or resolved is None:
        return None
    aware = [dt.tzinfo is not None for dt in (started, detected, resolved)]
    if any(aware) and not all(aware):
        return None
    if detected < started or resolved < detected:
        return None
    return ResponseMetrics(
        time_to_detect=detected - started,
        time_to_resolve=resolved - detected,
        total_duration=resolved - started,
    )


def _format_duration(delta: timedelta) -> str:
    minutes = round(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rem = divmod(minutes, 60)
    text = f"{hours} hour{'s' if hours != 1 else ''}"
    if rem:
        text += f" {rem} minute{'s' if rem != 1 else ''}"
    return text


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
    ]
    metrics = response_metrics(incident)
    if metrics is not None:
        lines += [
            "## Response metrics",
            "",
            f"- **Time to detect:** {_format_duration(metrics.time_to_detect)} (start to detection)",
            f"- **Time to resolve:** {_format_duration(metrics.time_to_resolve)} (detection to resolution)",
            f"- **Total duration:** {_format_duration(metrics.total_duration)}",
            "",
        ]
    lines += ["## Timeline", ""]
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
