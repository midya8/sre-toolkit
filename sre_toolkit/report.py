"""Render a Markdown SLO status report from window snapshots.

Each snapshot is one SLO's observed window (name, target, totals). The
report renders a Markdown table plus a plain-language status line per SLO,
suitable for pasting into a status doc or chat.
"""

from __future__ import annotations

from dataclasses import dataclass

from .error_budget import compute_error_budget, time_to_exhaustion_days


@dataclass(frozen=True)
class SLOSnapshot:
    """One SLO's observed window: name, target fraction, and event counts.

    When ``window_days`` is set, the status line also projects when the
    budget exhausts at the current burn.
    """

    name: str
    slo: float
    total_events: int
    bad_events: int
    window_days: float | None = None


def classify_status(snapshot: SLOSnapshot) -> str:
    """One-word status: no_events, exhausted, nearly_exhausted, or healthy."""
    if snapshot.total_events == 0:
        return "no_events"
    budget = compute_error_budget(
        snapshot.slo, snapshot.total_events, snapshot.bad_events
    )
    if budget.remaining_fraction <= 0:
        return "exhausted"
    if budget.consumed_fraction >= 0.8:
        return "nearly_exhausted"
    return "healthy"


def snapshot_summary(snapshot: SLOSnapshot) -> dict:
    """Machine-readable budget detail for one snapshot.

    ``error_rate``, ``consumed_fraction``, ``burn_rate`` and
    ``remaining_fraction`` are None when no events were recorded;
    ``exhaustion_days`` is None without a window or under zero burn.
    """
    status = classify_status(snapshot)
    summary = {
        "name": snapshot.name,
        "slo": snapshot.slo,
        "total_events": snapshot.total_events,
        "bad_events": snapshot.bad_events,
        "status": status,
        "error_rate": None,
        "consumed_fraction": None,
        "burn_rate": None,
        "remaining_fraction": None,
        "exhaustion_days": None,
    }
    if snapshot.total_events == 0:
        return summary
    budget = compute_error_budget(
        snapshot.slo, snapshot.total_events, snapshot.bad_events
    )
    summary.update({
        "error_rate": snapshot.bad_events / snapshot.total_events,
        "consumed_fraction": budget.consumed_fraction,
        "burn_rate": budget.burn_rate,
        "remaining_fraction": budget.remaining_fraction,
    })
    if snapshot.window_days is not None and status != "exhausted":
        summary["exhaustion_days"] = time_to_exhaustion_days(budget, snapshot.window_days)
    return summary


def _exhaustion_projection(snapshot: SLOSnapshot) -> str:
    """Projection sentence for the status line, or empty when not applicable."""
    if snapshot.window_days is None:
        return ""
    budget = compute_error_budget(
        snapshot.slo, snapshot.total_events, snapshot.bad_events
    )
    days = time_to_exhaustion_days(budget, snapshot.window_days)
    if days is None:
        return " Zero burn: no exhaustion projected."
    if days <= 0:
        return ""
    return f" At current burn the budget exhausts in ~{days:.1f} days."


def _status_line(snapshot: SLOSnapshot) -> str:
    if snapshot.total_events == 0:
        return f"- **{snapshot.name}**: no events recorded in the window."
    budget = compute_error_budget(
        snapshot.slo, snapshot.total_events, snapshot.bad_events
    )
    if budget.remaining_fraction <= 0:
        return (
            f"- **{snapshot.name}**: error budget exhausted "
            f"({budget.consumed_fraction:.0%} consumed)."
        )
    projection = _exhaustion_projection(snapshot)
    if budget.consumed_fraction >= 0.8:
        return (
            f"- **{snapshot.name}**: budget nearly exhausted "
            f"({budget.consumed_fraction:.0%} consumed).{projection}"
        )
    return (
        f"- **{snapshot.name}**: healthy "
        f"({budget.consumed_fraction:.0%} of budget consumed).{projection}"
    )


def render_report(snapshots: list[SLOSnapshot]) -> str:
    """Render snapshots as a Markdown SLO status report."""
    lines = [
        "# SLO status report",
        "",
        "| SLO | Target | Error rate | Budget consumed | Burn rate |",
        "| --- | --- | --- | --- | --- |",
    ]
    if not snapshots:
        lines.append("| _no SLOs_ | | | | |")
        lines.append("")
        return "\n".join(lines) + "\n"
    for snap in snapshots:
        if snap.total_events == 0:
            lines.append(f"| {snap.name} | {snap.slo:.2%} | n/a | n/a | n/a |")
            continue
        budget = compute_error_budget(snap.slo, snap.total_events, snap.bad_events)
        error_ratio = snap.bad_events / snap.total_events
        lines.append(
            f"| {snap.name} | {snap.slo:.2%} | {error_ratio:.4%} | "
            f"{budget.consumed_fraction:.1%} | {budget.burn_rate:.2f}x |"
        )
    lines.append("")
    lines.append("## Status")
    lines.append("")
    lines.extend(_status_line(snap) for snap in snapshots)
    return "\n".join(lines) + "\n"
