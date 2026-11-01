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


def consumed_fraction(snapshot: SLOSnapshot) -> float:
    """Budget consumed for sort order; SLOs with no events sort last."""
    if snapshot.total_events == 0:
        return -1.0
    return compute_error_budget(
        snapshot.slo, snapshot.total_events, snapshot.bad_events
    ).consumed_fraction


def render_report(snapshots: list[SLOSnapshot], worst_first: bool = False,
                  include_summary: bool = False) -> str:
    """Render snapshots as a Markdown SLO status report.

    With ``worst_first``, rows and status lines sort by budget consumed
    (most consumed first) so a long fleet review surfaces the SLOs that
    need action; input order is preserved otherwise. ``include_summary``
    appends a fleet roll-up section (counts per status class, worst SLO).
    """
    ordered = (
        sorted(snapshots, key=consumed_fraction, reverse=True)
        if worst_first
        else snapshots
    )
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
    for snap in ordered:
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
    lines.extend(_status_line(snap) for snap in ordered)
    if include_summary:
        summary = fleet_summary(snapshots)
        lines.extend([
            "",
            "## Fleet summary",
            "",
            f"- {summary['slos']} SLOs: {summary['healthy']} healthy, "
            f"{summary['nearly_exhausted']} nearly exhausted, "
            f"{summary['exhausted']} exhausted "
            f"({summary['no_events']} without events)",
        ])
        if summary["worst_slo"] is not None:
            lines.append(
                f"- Worst: {summary['worst_slo']} "
                f"(budget {summary['worst_consumed_fraction']:.1%} consumed)")
        else:
            lines.append("- Worst: n/a (no events recorded)")
    return "\n".join(lines) + "\n"


def fleet_summary(snapshots: list[SLOSnapshot]) -> dict:
    """Fleet roll-up across every snapshot: counts per status class.

    One glance answers "how is the fleet?" instead of scanning rows.
    ``worst_slo`` names the most-consumed SLO among those with events
    (None when the fleet is empty or has no events at all).
    """
    counts = {"healthy": 0, "nearly_exhausted": 0, "exhausted": 0, "no_events": 0}
    for snap in snapshots:
        counts[classify_status(snap)] += 1
    active = [snap for snap in snapshots if snap.total_events > 0]
    worst = max(active, key=consumed_fraction, default=None)
    return {
        "slos": len(snapshots),
        **counts,
        "worst_slo": worst.name if worst else None,
        "worst_consumed_fraction": (
            consumed_fraction(worst) if worst else None),
    }
