"""Multi-window burn-rate alerting for one SLO.

Implements the classic SRE-workbook pattern: an alert fires only when the
burn rate is elevated over BOTH a long window and a short window, so a
brief blip cannot page anyone and a slow leak still gets caught.

Default rules:
    page   - burn >= 14.4x sustained over 1h and 5m   (budget gone in 2 days)
    ticket - burn >= 6x sustained over 6h and 30m     (budget gone in 5 days)
"""

from __future__ import annotations

from dataclasses import dataclass

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
