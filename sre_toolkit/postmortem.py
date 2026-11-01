"""Postmortem document generation from structured incident data."""

from __future__ import annotations

import math
import statistics
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


@dataclass(frozen=True)
class IncidentStats:
    """Response-metric aggregates over a set of incidents.

    ``skipped`` counts incidents whose timestamps did not yield metrics -
    they are excluded from the aggregates, never silently averaged in.
    The p90 fields use nearest-rank, so with few incidents they equal the
    worst incident - honest for small samples.
    """

    incidents: int
    skipped: int
    mean_time_to_detect: timedelta
    median_time_to_detect: timedelta
    p90_time_to_detect: timedelta
    mean_time_to_resolve: timedelta
    median_time_to_resolve: timedelta
    p90_time_to_resolve: timedelta


def _percentile(deltas: list[timedelta], pct: float) -> timedelta:
    """Nearest-rank percentile over timedeltas."""
    ordered = sorted(deltas)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize_incidents(incidents: list[Incident]) -> IncidentStats | None:
    """Aggregate time-to-detect and time-to-resolve across incidents.

    Incidents whose timestamps are unparseable or out of order are
    skipped. Returns None when no incident yields computable metrics.
    """
    metrics = [m for m in (response_metrics(i) for i in incidents) if m is not None]
    if not metrics:
        return None
    ttds = [m.time_to_detect for m in metrics]
    ttrs = [m.time_to_resolve for m in metrics]
    return IncidentStats(
        incidents=len(metrics),
        skipped=len(incidents) - len(metrics),
        mean_time_to_detect=sum(ttds, timedelta()) / len(ttds),
        median_time_to_detect=statistics.median(ttds),
        p90_time_to_detect=_percentile(ttds, 90),
        mean_time_to_resolve=sum(ttrs, timedelta()) / len(ttrs),
        median_time_to_resolve=statistics.median(ttrs),
        p90_time_to_resolve=_percentile(ttrs, 90),
    )


def summarize_by_severity(incidents: list[Incident]) -> dict[str, "IncidentStats"]:
    """Per-severity response-metric aggregates.

    MTTR only means something split by severity - a 4-hour low-severity fix
    tells a different story than a 4-hour critical. Severities with no
    computable incidents are omitted.
    """
    groups: dict[str, list[Incident]] = {}
    for incident in incidents:
        groups.setdefault(incident.severity, []).append(incident)
    result = {}
    for severity, group in groups.items():
        stats = summarize_incidents(group)
        if stats is not None:
            result[severity] = stats
    return result


def summarize_by_week(incidents: list[Incident]) -> list[tuple[str, "IncidentStats"]]:
    """Weekly response-metric aggregates, oldest week first.

    A single MTTR over a quarter hides the trend - "are we getting
    faster?" needs the same aggregates bucketed by week. Incidents group
    by the ISO week of their resolved timestamp; incidents whose resolved
    time is unparseable are skipped, matching summarize_incidents.
    """
    groups: dict[tuple[int, int], list[Incident]] = {}
    for incident in incidents:
        resolved = _parse_timestamp(incident.resolved)
        if resolved is None:
            continue
        iso = resolved.isocalendar()
        groups.setdefault((iso[0], iso[1]), []).append(incident)
    result = []
    for (year, week), group in sorted(groups.items()):
        stats = summarize_incidents(group)
        if stats is not None:
            result.append((f"{year}-W{week:02d}", stats))
    return result


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


def summarize_by_service(incidents: list[Incident]) -> dict[str, "IncidentStats"]:
    """Per-service response-metric aggregates.

    An incident lists every service it touched, so it counts toward each
    of them; incidents with no services recorded are omitted. Answers
    "which service eats our response time?". Services with no computable
    incidents are omitted, matching summarize_by_severity.
    """
    groups: dict[str, list[Incident]] = {}
    for incident in incidents:
        for service in incident.services:
            groups.setdefault(service, []).append(incident)
    result = {}
    for service, group in groups.items():
        stats = summarize_incidents(group)
        if stats is not None:
            result[service] = stats
    return result
