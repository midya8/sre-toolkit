"""Render a Markdown SLO status report from window snapshots.

Each snapshot is one SLO's observed window (name, target, totals). The
report renders a Markdown table plus a plain-language status line per SLO,
suitable for pasting into a status doc or chat.
"""

from __future__ import annotations

from dataclasses import dataclass

from .error_budget import compute_error_budget


@dataclass(frozen=True)
class SLOSnapshot:
    """One SLO's observed window: name, target fraction, and event counts."""

    name: str
    slo: float
    total_events: int
    bad_events: int


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
    if budget.consumed_fraction >= 0.8:
        return (
            f"- **{snapshot.name}**: budget nearly exhausted "
            f"({budget.consumed_fraction:.0%} consumed)."
        )
    return (
        f"- **{snapshot.name}**: healthy "
        f"({budget.consumed_fraction:.0%} of budget consumed)."
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
