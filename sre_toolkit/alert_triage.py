"""Rule-based alert triage: severity classification, dedupe, grouping.

The goal is a boring, predictable first pass over an alert stream so an
on-call engineer sees each distinct problem once, in priority order.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY_ORDER = ("critical", "high", "medium", "low")

_DEFAULT_RULES = (
    ("critical", ("page", "outage", "down", "unreachable", "data loss")),
    ("high", ("degraded", "error rate", "latency", "timeout", "failing")),
    ("medium", ("warning", "elevated", "approaching", "retry")),
)


@dataclass(frozen=True)
class Alert:
    """One incoming alert."""

    alert_id: str
    service: str
    summary: str
    severity: str = ""
    labels: dict = field(default_factory=dict)


def classify_severity(summary: str, rules=_DEFAULT_RULES) -> str:
    """Classify an alert summary into a severity using keyword rules.

    The first matching rule wins, checked from most to least severe.
    Summaries matching nothing are ``low``.
    """
    text = summary.lower()
    for severity, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return severity
    return "low"


def dedupe(alerts: list[Alert]) -> list[Alert]:
    """Collapse alerts that share (service, normalized summary).

    The first occurrence wins; later duplicates are dropped. Order of the
    survivors is preserved.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[Alert] = []
    for alert in alerts:
        key = (alert.service, " ".join(alert.summary.lower().split()))
        if key not in seen:
            seen.add(key)
            unique.append(alert)
    return unique


def triage(alerts: list[Alert], rules=_DEFAULT_RULES) -> list[Alert]:
    """Classify, dedupe and sort alerts by severity then service.

    Any explicit severity on the alert is kept; empty/missing severities
    are classified from the summary. Unknown explicit severities are
    treated as ``low``.
    """
    classified = []
    for alert in alerts:
        severity = alert.severity if alert.severity in SEVERITY_ORDER else ""
        if not severity:
            severity = classify_severity(alert.summary, rules)
        classified.append(
            Alert(
                alert_id=alert.alert_id,
                service=alert.service,
                summary=alert.summary,
                severity=severity,
                labels=alert.labels,
            )
        )
    unique = dedupe(classified)
    rank = {severity: index for index, severity in enumerate(SEVERITY_ORDER)}
    return sorted(unique, key=lambda a: (rank[a.severity], a.service, a.alert_id))


def group_by_service(alerts: list[Alert]) -> dict[str, list[Alert]]:
    """Group alerts by service, preserving each alert's input order."""
    grouped: dict[str, list[Alert]] = {}
    for alert in alerts:
        grouped.setdefault(alert.service, []).append(alert)
    return grouped
