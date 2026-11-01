"""Render an SLO definition as a Markdown document.

SLOs that live only in a dashboard get forgotten. Rendering the
definition - target, window, SLI, budget, alerting policy - as Markdown
keeps it reviewable in the repo next to the service it covers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .error_budget import allowed_downtime_minutes


@dataclass(frozen=True)
class SLODefinition:
    """One service-level objective definition.

    Attributes:
        name: Human-readable objective name, e.g. "Checkout availability".
        service: Service the objective covers.
        target: Availability target as a fraction, e.g. 0.999.
        window_days: Rolling compliance window in days.
        sli: The measured indicator, in plain language.
        description: Optional context paragraph.
        alert_thresholds: Optional burn-rate alert descriptions, e.g.
            ("page at 14.4x over 1h+5m",).
    """

    name: str
    service: str
    target: float
    window_days: float
    sli: str
    description: str = ""
    alert_thresholds: tuple[str, ...] = ()


def render_slo_doc(definition: SLODefinition) -> str:
    """Render an SLO definition as a Markdown document."""
    if not 0.0 < definition.target < 1.0:
        raise ValueError(f"target must be between 0 and 1 exclusive, got {definition.target!r}")
    if definition.window_days <= 0:
        raise ValueError(f"window_days must be positive, got {definition.window_days!r}")

    d = definition
    lines = [
        f"# SLO: {d.name}",
        "",
        f"- **Service:** {d.service}",
        f"- **Target:** {d.target:.2%}",
        f"- **Window:** {d.window_days:g} days (rolling)",
        f"- **SLI:** {d.sli}",
        "",
    ]
    if d.description:
        lines.extend([d.description, ""])

    budget_fraction = 1.0 - d.target
    downtime = allowed_downtime_minutes(d.target, d.window_days)
    lines.extend([
        "## Error budget",
        "",
        f"- Budget fraction: {budget_fraction:.3%} of requests may fail.",
        f"- Equivalent to {downtime:.1f} minutes of full outage per "
        f"{d.window_days:g}-day window.",
        "",
    ])

    lines.extend(["## Alerting", ""])
    if d.alert_thresholds:
        for threshold in d.alert_thresholds:
            lines.append(f"- {threshold}")
    else:
        lines.append("- _No alert thresholds defined._")
    lines.append("")
    return "\n".join(lines)
