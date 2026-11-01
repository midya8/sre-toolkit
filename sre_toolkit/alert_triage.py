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


def rules_from_dict(data: dict) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Build triage rules from a JSON mapping of severity to keywords.

    Example: {"critical": ["page", "outage"], "high": ["degraded"]}.
    Severities must come from SEVERITY_ORDER so sorting stays meaningful;
    rules are returned most-severe-first regardless of input order. Raises
    ValueError on unknown severities, non-list keywords, or empty lists.
    """
    if not isinstance(data, dict) or not data:
        raise ValueError("rules must be a JSON object mapping severity to keywords")
    unknown = set(data) - set(SEVERITY_ORDER)
    if unknown:
        raise ValueError(f"unknown severities: {sorted(unknown)} "
                         f"(want a subset of {list(SEVERITY_ORDER)})")
    rules = []
    for severity in SEVERITY_ORDER:
        if severity not in data:
            continue
        keywords = data[severity]
        if not isinstance(keywords, list) or not keywords or \
                not all(isinstance(k, str) and k for k in keywords):
            raise ValueError(f"{severity!r} keywords must be a non-empty list of strings")
        rules.append((severity, tuple(keywords)))
    return tuple(rules)


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


def dedupe_key(alert: Alert) -> tuple[str, str]:
    """The identity ``dedupe`` uses: (service, normalized summary)."""
    return (alert.service, " ".join(alert.summary.lower().split()))


def dedupe(alerts: list[Alert]) -> list[Alert]:
    """Collapse alerts that share (service, normalized summary).

    The first occurrence wins; later duplicates are dropped. Order of the
    survivors is preserved.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[Alert] = []
    for alert in alerts:
        key = dedupe_key(alert)
        if key not in seen:
            seen.add(key)
            unique.append(alert)
    return unique


def duplicate_counts(alerts: list[Alert]) -> dict[tuple[str, str], int]:
    """Occurrence count per ``dedupe_key`` over the raw alert stream.

    Every survivor of ``dedupe`` maps to a count of at least 1; a count
    above 1 means the alert fired repeatedly. The volume matters next to
    each distinct problem - one flap and a hundred repeats read alike
    after dedupe alone.
    """
    counts: dict[tuple[str, str], int] = {}
    for alert in alerts:
        key = dedupe_key(alert)
        counts[key] = counts.get(key, 0) + 1
    return counts


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


def inhibit_by_critical(alerts: list[Alert]) -> tuple[list[Alert], list[Alert]]:
    """Suppress lower-severity alerts on services with an active critical.

    Same idea as Alertmanager inhibit rules: when a service is in a known
    outage, its high/medium/low alerts are symptoms of the same fire, and
    paging on them too only buries the cause. Returns (kept, inhibited),
    both preserving input order.
    """
    critical_services = {a.service for a in alerts if a.severity == "critical"}
    kept, inhibited = [], []
    for alert in alerts:
        if alert.severity != "critical" and alert.service in critical_services:
            inhibited.append(alert)
        else:
            kept.append(alert)
    return kept, inhibited


def group_by_service(alerts: list[Alert]) -> dict[str, list[Alert]]:
    """Group alerts by service, preserving each alert's input order."""
    grouped: dict[str, list[Alert]] = {}
    for alert in alerts:
        grouped.setdefault(alert.service, []).append(alert)
    return grouped
