"""Postmortem document generation from structured incident data."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


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


def parse_action_item(raw: object, where: str = "action item") -> tuple[str, bool]:
    """Normalize one action item to (text, done).

    Accepts a plain string (an open item, the historical shape) or an
    object like {"item": "...", "done": true} - also "task"/"text" for
    the text key. Anything else is a ValueError naming the offender.
    """
    if isinstance(raw, str):
        if not raw.strip():
            raise ValueError(f"{where}: empty action item text")
        return raw, False
    if isinstance(raw, dict):
        unknown = set(raw) - {"item", "task", "text", "done"}
        if unknown:
            raise ValueError(f"{where} has unknown keys: {sorted(unknown)}")
        text = raw.get("item") or raw.get("task") or raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{where}: needs a non-empty 'item' text")
        done = raw.get("done", False)
        if not isinstance(done, bool):
            raise ValueError(f"{where}: 'done' must be true or false")
        return text, done
    raise ValueError(f"{where} must be a string or an object")


def action_item_followup(incidents: list[dict], now: datetime | None = None,
                         stale_days: float = 14.0) -> dict:
    """Follow-through report across incidents: which action items are still open.

    An incident is "stale" when it was resolved more than ``stale_days``
    ago and still has open items - the postmortem did its analysis but
    the fixes never landed. Incidents whose resolved timestamp does not
    parse report open items without an age. Returns per-incident detail
    plus totals, ordered most-open-items first.
    """
    now = now or datetime.now(tz=timezone.utc)
    entries = []
    open_total = 0
    stale_total = 0
    for raw in incidents:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "(untitled incident)"))
        items = raw.get("action_items") or []
        open_items = []
        for i, item_raw in enumerate(items):
            text, done = parse_action_item(item_raw, f"{title!r} action item #{i + 1}")
            if not done:
                open_items.append(text)
        if not open_items:
            continue
        resolved = _parse_timestamp(str(raw.get("resolved", "")))
        age_days = None
        stale = False
        if resolved is not None:
            if resolved.tzinfo is None:
                resolved = resolved.replace(tzinfo=timezone.utc)
            age_days = (now - resolved).total_seconds() / 86400.0
            stale = age_days > stale_days
        open_total += len(open_items)
        stale_total += 1 if stale else 0
        entries.append({
            "title": title,
            "open_items": open_items,
            "open_count": len(open_items),
            "days_since_resolved": None if age_days is None else round(age_days, 1),
            "stale": stale,
        })
    entries.sort(key=lambda e: (-e["open_count"], e["title"]))
    return {
        "incidents_with_open_items": len(entries),
        "open_items_total": open_total,
        "stale_incidents": stale_total,
        "stale_days": stale_days,
        "incidents": entries,
    }


def format_action_item_followup(report: dict) -> str:
    """Render the follow-through report as a plain-text block."""
    lines = [
        f"Action items: {report['open_items_total']} open across "
        f"{report['incidents_with_open_items']} incidents "
        f"({report['stale_incidents']} stale > {report['stale_days']:g} days)",
    ]
    for entry in report["incidents"]:
        age = entry["days_since_resolved"]
        age_text = "unknown age" if age is None else f"resolved {age:g}d ago"
        flag = " STALE" if entry["stale"] else ""
        lines.append(f"  {entry['title']} ({age_text}){flag}")
        for item in entry["open_items"]:
            lines.append(f"    - [ ] {item}")
    if not report["incidents"]:
        lines.append("  All recorded action items are done.")
    return "\n".join(lines)
