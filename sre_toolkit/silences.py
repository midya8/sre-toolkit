"""Alertmanager-style silences for the triage stream.

A silence says "we know about this; stop showing it" for a bounded
time. Alerts matching every matcher a silence sets (service, severity,
and/or a case-insensitive substring of the summary) are pulled out of
the triaged list while the silence is active, and shown separately with
the reason so a silenced fire is visible, not vanished.

Silences are validated strictly: unknown keys, bad types, and
unparseable ``until`` timestamps are errors, because a silence that
silently does nothing pages nobody when it should have.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .alert_triage import SEVERITY_ORDER, Alert

_SILENCE_KEYS = {"service", "severity", "contains", "reason", "until"}


@dataclass(frozen=True)
class Silence:
    """One silence: matchers plus a reason and an expiry.

    Every matcher that is set must match for the silence to apply;
    unset matchers match everything. ``until`` is timezone-aware; the
    silence is active strictly before that instant.
    """

    reason: str
    until: datetime
    service: str | None = None
    severity: str | None = None
    contains: str | None = None

    def is_active(self, now: datetime) -> bool:
        return now < self.until

    def matches(self, alert: Alert) -> bool:
        if self.service is not None and alert.service != self.service:
            return False
        if self.severity is not None and alert.severity != self.severity:
            return False
        if self.contains is not None and \
                self.contains.lower() not in alert.summary.lower():
            return False
        return True


def _parse_until(value: object, where: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{where}: 'until' must be an ISO-8601 timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{where}: unparseable 'until' timestamp {value!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def silence_from_dict(data: dict, where: str = "silence") -> Silence:
    """Validate one JSON object into a Silence. Raises ValueError on any problem."""
    if not isinstance(data, dict):
        raise ValueError(f"{where} must be an object")
    unknown = set(data) - _SILENCE_KEYS
    if unknown:
        raise ValueError(f"{where} has unknown keys: {sorted(unknown)}")
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(f"{where} needs a non-empty string 'reason'")
    if "until" not in data:
        raise ValueError(f"{where} needs an 'until' timestamp")
    until = _parse_until(data["until"], where)
    service = data.get("service")
    if service is not None and not isinstance(service, str):
        raise ValueError(f"{where}: 'service' must be a string")
    severity = data.get("severity")
    if severity is not None:
        if severity not in SEVERITY_ORDER:
            raise ValueError(f"{where}: 'severity' must be one of {list(SEVERITY_ORDER)}")
    contains = data.get("contains")
    if contains is not None and (not isinstance(contains, str) or not contains):
        raise ValueError(f"{where}: 'contains' must be a non-empty string")
    if service is None and severity is None and contains is None:
        raise ValueError(f"{where} sets no matchers - it would silence everything")
    return Silence(reason=reason, until=until, service=service,
                   severity=severity, contains=contains)


def load_silences(data: list) -> list[Silence]:
    """Validate a parsed JSON list of silences."""
    if not isinstance(data, list):
        raise ValueError("silences file must be a JSON list")
    return [silence_from_dict(item, f"silence #{i + 1}")
            for i, item in enumerate(data)]


def apply_silences(alerts: list[Alert], silences: list[Silence],
                   now: datetime | None = None) -> tuple[list[Alert], list[tuple[Alert, Silence]]]:
    """Split alerts into (kept, silenced pairs).

    An alert is silenced by the first active silence that matches it;
    the pair keeps the silence so the reason can be shown. Expired
    silences match nothing. Input order is preserved in both lists.
    """
    now = now or datetime.now(timezone.utc)
    active = [s for s in silences if s.is_active(now)]
    kept: list[Alert] = []
    silenced: list[tuple[Alert, Silence]] = []
    for alert in alerts:
        match = next((s for s in active if s.matches(alert)), None)
        if match is None:
            kept.append(alert)
        else:
            silenced.append((alert, match))
    return kept, silenced
