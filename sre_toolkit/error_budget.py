"""Error-budget and burn-rate calculations for a single SLO.

The math follows the standard SRE workbook definitions:

- The error budget for an SLO of ``slo`` over a window is ``1 - slo``.
- Budget consumed is the observed bad-event ratio divided by the budget.
- Burn rate is the observed error ratio relative to the budget over the
  same window; a burn rate of 1 consumes the budget exactly at the pace
  the window allows, and sustained burn above 1 exhausts it early.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorBudget:
    """Computed state of one SLO's error budget.

    Attributes:
        slo: The SLO target as a fraction, e.g. 0.999 for 99.9%.
        total_events: Events observed in the window.
        bad_events: Events in the window that violated the SLO.
        budget_fraction: Allowed bad-event fraction (1 - slo).
        consumed_fraction: Share of the budget already consumed (0-1+).
        burn_rate: Current consumption speed relative to budget pace.
        remaining_fraction: Budget still available (may be negative).
    """

    slo: float
    total_events: int
    bad_events: int
    budget_fraction: float
    consumed_fraction: float
    burn_rate: float
    remaining_fraction: float


def _validate(slo: float, total_events: int, bad_events: int) -> None:
    if not 0.0 < slo < 1.0:
        raise ValueError(f"slo must be between 0 and 1 exclusive, got {slo!r}")
    if total_events <= 0:
        raise ValueError(f"total_events must be positive, got {total_events!r}")
    if not 0 <= bad_events <= total_events:
        raise ValueError(
            f"bad_events must be within [0, total_events], got {bad_events!r}"
        )


def compute_error_budget(slo: float, total_events: int, bad_events: int) -> ErrorBudget:
    """Compute the error-budget state for one SLO window."""
    _validate(slo, total_events, bad_events)
    budget_fraction = 1.0 - slo
    error_ratio = bad_events / total_events
    consumed = error_ratio / budget_fraction
    return ErrorBudget(
        slo=slo,
        total_events=total_events,
        bad_events=bad_events,
        budget_fraction=budget_fraction,
        consumed_fraction=consumed,
        burn_rate=consumed,
        remaining_fraction=1.0 - consumed,
    )


def allowed_downtime_minutes(slo: float, window_days: float) -> float:
    """Return the error budget as minutes of full outage in the window."""
    _validate(slo, 1, 0)
    if window_days <= 0:
        raise ValueError(f"window_days must be positive, got {window_days!r}")
    return (1.0 - slo) * window_days * 24.0 * 60.0


def time_to_exhaustion_days(budget: ErrorBudget, window_days: float) -> float | None:
    """Project days until the budget is exhausted at the current burn rate.

    Returns None when nothing has been burned (burn rate is zero), since
    exhaustion is not projected under zero burn.
    """
    if budget.burn_rate <= 0:
        return None
    if window_days <= 0:
        raise ValueError(f"window_days must be positive, got {window_days!r}")
    elapsed = window_days * budget.consumed_fraction
    return budget.remaining_fraction * (elapsed / budget.consumed_fraction) if elapsed else 0.0
