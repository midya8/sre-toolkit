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
