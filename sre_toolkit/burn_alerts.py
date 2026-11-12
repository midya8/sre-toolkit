"""Multi-window burn-rate alerting for one SLO.

Implements the classic SRE-workbook pattern: an alert fires only when the
burn rate is elevated over BOTH a long window and a short window. This
filters some short spikes; it does not guarantee that a spike cannot page.

Default rules:
    page   - burn >= 14.4x sustained over 1h and 5m   (budget gone in 2 days)
    ticket - burn >= 6x sustained over 6h and 30m     (budget gone in 5 days)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .error_budget import compute_error_budget


@dataclass(frozen=True)
class BurnSample:
    """Observed events over one trailing window.

    window_hours is informational (kept for reporting); the burn-rate math
    only needs the event counts, since burn rate is window-independent.
    """

    window_hours: float
    total_events: int
    bad_events: int


@dataclass(frozen=True)
class BurnRule:
    """One alerting rule: burn threshold plus its long/short window pair."""

    name: str
    severity: str
    burn_threshold: float
    long_window_hours: float
    short_window_hours: float


DEFAULT_RULES = (
    BurnRule("page", "critical", 14.4, 1.0, 5.0 / 60.0),
    BurnRule("ticket", "high", 6.0, 6.0, 0.5),
)


def suggest_rules(slo: float, window_days: float = 30.0) -> tuple[BurnRule, ...]:
    """The standard three-tier multi-window policy for an SLO window.

    From the SRE workbook alerting table, generalized to any window:
    a page when 2% of the window's budget burns in one hour, a fast
    ticket at 5% in six hours, and a slow ticket at 10% in three days.
    Burn thresholds scale with the window (14.4x / 6x / 1x at 30 days);
    the windows themselves do not. Raises ValueError for an SLO outside
    (0, 1) or a window too short to hold the three-day rule.
    """
    if not 0 < slo < 1:
        raise ValueError(f"slo must be between 0 and 1, got {slo!r}")
    if window_days < 3:
        raise ValueError(
            f"window must be at least 3 days for the slow-burn rule, got {window_days!r}")
    window_hours = window_days * 24.0

    def burn_for(budget_fraction: float, hours: float) -> float:
        # The burn rate that consumes budget_fraction of the window's
        # budget within `hours`: fraction / (hours / total_hours).
        return budget_fraction / (hours / window_hours)

    return (
        BurnRule("page", "critical", round(burn_for(0.02, 1.0), 3), 1.0, 5.0 / 60.0),
        BurnRule("ticket-fast", "high", round(burn_for(0.05, 6.0), 3), 6.0, 0.5),
        BurnRule("ticket-slow", "medium", round(burn_for(0.1, 72.0), 3), 72.0, 6.0),
    )


def burn_rate(slo: float, total_events: int, bad_events: int) -> float:
    """Burn rate for one window: observed error ratio relative to budget."""
    return compute_error_budget(slo, total_events, bad_events).burn_rate


def _nearest(samples: list[BurnSample], window_hours: float) -> BurnSample | None:
    """Return the sample closest to the requested window, within 50%."""
    best: BurnSample | None = None
    for sample in samples:
        ratio = sample.window_hours / window_hours if window_hours else 0
        if 0.5 <= ratio <= 1.5 and (
            best is None
            or abs(sample.window_hours - window_hours) < abs(best.window_hours - window_hours)
        ):
            best = sample
    return best


def evaluate_rules(
    slo: float,
    samples: list[BurnSample],
    rules: tuple[BurnRule, ...] = DEFAULT_RULES,
) -> list[BurnRule]:
    """Return the rules currently firing, most severe first.

    A rule fires only when burn rate meets its threshold on BOTH its long
    and its short window. Rules whose windows have no usable sample are
    skipped rather than assumed quiet.
    """
    firing = []
    for rule in rules:
        long_sample = _nearest(samples, rule.long_window_hours)
        short_sample = _nearest(samples, rule.short_window_hours)
        if long_sample is None or short_sample is None:
            continue
        long_burn = burn_rate(slo, long_sample.total_events, long_sample.bad_events)
        short_burn = burn_rate(slo, short_sample.total_events, short_sample.bad_events)
        # Float burn rates can land an epsilon below a round threshold.
        eps = 1e-9
        if long_burn >= rule.burn_threshold - eps and short_burn >= rule.burn_threshold - eps:
            firing.append(rule)
    severity_rank = {"critical": 0, "high": 1}
    return sorted(firing, key=lambda r: severity_rank.get(r.severity, 2))


def _parse_bucket_ts(raw: object, where: str) -> datetime:
    """One bucket timestamp: ISO-8601, naive values assumed UTC."""
    if not isinstance(raw, str):
        raise ValueError(f"{where}: timestamp must be a string, got {raw!r}")
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{where}: unparseable timestamp {raw!r}") from exc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def replay_rules(
    slo: float,
    buckets: list[dict],
    rules: tuple[BurnRule, ...] = DEFAULT_RULES,
) -> list[dict]:
    """Replay a time series of observations through the burn rules.

    ``buckets`` are point observations -
    ``{"timestamp": ISO-8601, "total": n, "bad": n}`` - and each bucket
    timestamp is a tick. At a tick t, a rule's window (t - w, t] sums the
    buckets whose timestamps fall inside it; the rule fires at that tick
    when both its long and short windows are evaluable (non-empty) and
    meet the burn threshold. The result lists, per rule, every firing
    interval (first to last consecutive firing tick) plus the firing
    tick count - the "would this policy have paged us, and for how long"
    answer for alert-policy tuning. Raises ValueError for bad buckets.
    """
    points: list[tuple[datetime, int, int]] = []
    for i, raw in enumerate(buckets):
        where = f"bucket #{i + 1}"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} must be an object")
        ts = _parse_bucket_ts(raw.get("timestamp"), where)
        try:
            total = int(raw["total"])
            bad = int(raw["bad"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{where}: needs integer 'total' and 'bad'") from exc
        if total < 0 or bad < 0 or bad > total:
            raise ValueError(
                f"{where}: bad must satisfy 0 <= bad <= total, "
                f"got total={total}, bad={bad}")
        points.append((ts, total, bad))
    if not points:
        raise ValueError("replay needs at least one bucket")
    points.sort(key=lambda point: point[0])
    ticks = sorted({ts for ts, _, _ in points})

    def window_burn(tick: datetime, hours: float) -> float | None:
        total = bad = 0
        start = tick - timedelta(hours=hours)
        for ts, t, b in points:
            if start < ts <= tick:
                total += t
                bad += b
        if total == 0:
            return None
        return burn_rate(slo, total, bad)

    eps = 1e-9
    severity_rank = {"critical": 0, "high": 1}
    reports = []
    for rule in rules:
        firing_idx = []
        for i, tick in enumerate(ticks):
            long_burn = window_burn(tick, rule.long_window_hours)
            short_burn = window_burn(tick, rule.short_window_hours)
            if (long_burn is not None and short_burn is not None
                    and long_burn >= rule.burn_threshold - eps
                    and short_burn >= rule.burn_threshold - eps):
                firing_idx.append(i)
        intervals = []
        for i in firing_idx:
            if intervals and i == intervals[-1]["_last_idx"] + 1:
                intervals[-1]["end"] = ticks[i]
                intervals[-1]["_last_idx"] = i
                intervals[-1]["ticks"] += 1
            else:
                intervals.append({"start": ticks[i], "end": ticks[i],
                                  "_last_idx": i, "ticks": 1})
        reports.append({
            "name": rule.name,
            "severity": rule.severity,
            "burn_threshold": rule.burn_threshold,
            "long_window_hours": rule.long_window_hours,
            "short_window_hours": rule.short_window_hours,
            "firing_ticks": len(firing_idx),
            "intervals": [{k: v for k, v in iv.items() if not k.startswith("_")}
                          for iv in intervals],
        })
    return sorted(reports, key=lambda r: severity_rank.get(r["severity"], 2))
