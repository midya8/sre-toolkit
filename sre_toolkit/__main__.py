"""Command-line entry point: ``python -m sre_toolkit``.

Subcommands:
    budget      error-budget math for one SLO window
    downtime    allowed downtime in minutes for an SLO over N days
    triage      classify a JSON list of alerts
    report      render a Markdown SLO status report from a JSON list
    burn        evaluate multi-window burn-rate rules from a JSON spec
    postmortem  render a Markdown postmortem from a JSON incident
    metrics     aggregate time-to-detect/resolve across incidents
    slo-doc     render a Markdown SLO definition from a JSON spec
"""

from __future__ import annotations

import argparse
import json
import sys

from .alert_triage import Alert, dedupe_key, duplicate_counts, group_by_service, inhibit_by_critical, triage
from .burn_alerts import BurnRule, BurnSample, evaluate_rules
from .error_budget import (
    allowed_downtime_minutes,
    compute_error_budget,
    time_to_exhaustion_days,
)
from .postmortem import Incident, _format_duration, render_postmortem, summarize_incidents
from .report import SLOSnapshot, render_report
from .slo_doc import SLODefinition, render_slo_doc


def _cmd_budget(args: argparse.Namespace) -> int:
    budget = compute_error_budget(args.slo, args.total, args.bad)
    print(f"SLO target:        {budget.slo:.4%}")
    print(f"Budget fraction:   {budget.budget_fraction:.4%}")
    print(f"Consumed:          {budget.consumed_fraction:.1%}")
    print(f"Remaining:         {budget.remaining_fraction:.1%}")
    print(f"Burn rate:         {budget.burn_rate:.2f}x")
    if args.window_days is not None:
        days = time_to_exhaustion_days(budget, args.window_days)
        if days is None:
            print("Exhaustion:        not projected (zero burn)")
        elif days <= 0:
            print("Exhaustion:        budget already exhausted")
        else:
            print(f"Exhaustion:        ~{days:.1f} days at current burn")
    return 0 if budget.remaining_fraction > 0 else 1


def _cmd_downtime(args: argparse.Namespace) -> int:
    if args.days is not None:
        minutes = allowed_downtime_minutes(args.slo, args.days)
        print(f"Allowed downtime: {minutes:.1f} minutes over {args.days:g} days")
        return 0
    print(f"Allowed downtime for SLO {args.slo:.3%}:")
    for window in (1, 7, 30, 90):
        minutes = allowed_downtime_minutes(args.slo, window)
        print(f"  {window:3d} days: {minutes:8.1f} minutes")
    return 0


def _cmd_triage(args: argparse.Namespace) -> int:
    raw = json.load(sys.stdin if args.file == "-" else open(args.file))
    incoming = [Alert(**item) for item in raw]
    counts = duplicate_counts(incoming)
    alerts = triage(incoming)
    inhibited: list[Alert] = []
    if args.inhibit:
        alerts, inhibited = inhibit_by_critical(alerts)

    def _suffix(alert: Alert) -> str:
        n = counts[dedupe_key(alert)]
        return f" (x{n})" if n > 1 else ""

    if args.json:
        payload = {"alerts": [
            {"alert_id": a.alert_id, "service": a.service,
             "summary": a.summary, "severity": a.severity,
             "occurrences": counts[dedupe_key(a)]}
            for a in alerts
        ]}
        if args.inhibit:
            payload["inhibited"] = [
                {"alert_id": a.alert_id, "service": a.service,
                 "summary": a.summary, "severity": a.severity,
                 "occurrences": counts[dedupe_key(a)]}
                for a in inhibited
            ]
            print(json.dumps(payload, indent=2))
        else:
            print(json.dumps(payload["alerts"], indent=2))
        return 0
    if args.by_service:
        for service, group in sorted(group_by_service(alerts).items()):
            worst = group[0].severity  # triage() sorts most severe first
            n = len(group)
            print(f"{service} ({n} alert{'' if n == 1 else 's'}, worst: {worst})")
            for alert in group:
                print(f"  [{alert.severity:8s}] {alert.summary}{_suffix(alert)}")
        return 0
    for alert in alerts:
        print(f"[{alert.severity:8s}] {alert.service:20s} {alert.summary}{_suffix(alert)}")
    if inhibited:
        print(f"({len(inhibited)} alert{'' if len(inhibited) == 1 else 's'} "
              f"inhibited: symptoms of a critical on the same service)")
        for alert in inhibited:
            print(f"  [{alert.severity:8s}] {alert.service:20s} {alert.summary}{_suffix(alert)}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    raw = json.load(sys.stdin if args.file == "-" else open(args.file))
    snapshots = [
        SLOSnapshot(
            name=item["name"],
            slo=float(item["slo"]),
            total_events=int(item["total"]),
            bad_events=int(item["bad"]),
            window_days=float(item["window_days"]) if "window_days" in item else None,
        )
        for item in raw
    ]
    print(render_report(snapshots), end="")
    exhausted = any(
        snap.total_events > 0
        and compute_error_budget(snap.slo, snap.total_events, snap.bad_events).remaining_fraction <= 0
        for snap in snapshots
    )
    return 1 if exhausted else 0


def _burn_rules(raw: list[dict]) -> tuple[BurnRule, ...] | None:
    """Build custom rules from the JSON spec, or None for the defaults."""
    if not raw:
        return None
    rules = []
    for item in raw:
        try:
            rules.append(BurnRule(
                name=str(item["name"]),
                severity=str(item["severity"]),
                burn_threshold=float(item["burn_threshold"]),
                long_window_hours=float(item["long_window_hours"]),
                short_window_hours=float(item["short_window_hours"]),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid burn rule {item!r}: {exc}") from exc
    return tuple(rules)


def _cmd_burn(args: argparse.Namespace) -> int:
    raw = json.load(sys.stdin if args.file == "-" else open(args.file))
    samples = [
        BurnSample(
            window_hours=float(item["window_hours"]),
            total_events=int(item["total"]),
            bad_events=int(item["bad"]),
        )
        for item in raw["samples"]
    ]
    try:
        rules = _burn_rules(raw.get("rules"))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if rules is None:
        firing = evaluate_rules(float(raw["slo"]), samples)
    else:
        firing = evaluate_rules(float(raw["slo"]), samples, rules=rules)
    if args.json:
        print(json.dumps({
            "slo": float(raw["slo"]),
            "firing": [
                {"name": r.name, "severity": r.severity,
                 "burn_threshold": r.burn_threshold,
                 "long_window_hours": r.long_window_hours,
                 "short_window_hours": r.short_window_hours}
                for r in firing
            ],
        }, indent=2))
        return 1 if any(rule.severity == "critical" for rule in firing) else 0
    if not firing:
        print("No burn-rate rules firing.")
        return 0
    for rule in firing:
        print(
            f"[{rule.severity:8s}] {rule.name}: burn >= {rule.burn_threshold:g}x "
            f"on both {rule.long_window_hours:g}h and {rule.short_window_hours * 60:g}m windows"
        )
    return 1 if any(rule.severity == "critical" for rule in firing) else 0


def _incident_from(raw: dict) -> Incident:
    return Incident(
        title=raw["title"],
        severity=raw["severity"],
        started=raw["started"],
        detected=raw["detected"],
        resolved=raw["resolved"],
        services=tuple(raw.get("services", ())),
        summary=raw["summary"],
        impact=raw["impact"],
        root_cause=raw["root_cause"],
        timeline=tuple(tuple(pair) for pair in raw.get("timeline", ())),
        action_items=tuple(raw.get("action_items", ())),
    )


def _cmd_postmortem(args: argparse.Namespace) -> int:
    raw = json.load(sys.stdin if args.file == "-" else open(args.file))
    print(render_postmortem(_incident_from(raw)), end="")
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    raw = json.load(sys.stdin if args.file == "-" else open(args.file))
    stats = summarize_incidents([_incident_from(item) for item in raw])
    if stats is None:
        print("error: no incidents with computable response metrics", file=sys.stderr)
        return 2
    skipped = f" ({stats.skipped} skipped, timestamps unparseable)" if stats.skipped else ""
    print(f"Incidents analyzed: {stats.incidents}{skipped}")
    print(f"Time to detect:  mean {_format_duration(stats.mean_time_to_detect)}, "
          f"median {_format_duration(stats.median_time_to_detect)}")
    print(f"Time to resolve: mean {_format_duration(stats.mean_time_to_resolve)}, "
          f"median {_format_duration(stats.median_time_to_resolve)}")
    return 0


def _cmd_slo_doc(args: argparse.Namespace) -> int:
    raw = json.load(sys.stdin if args.file == "-" else open(args.file))
    definition = SLODefinition(
        name=raw["name"],
        service=raw["service"],
        target=float(raw["target"]),
        window_days=float(raw["window_days"]),
        sli=raw["sli"],
        description=raw.get("description", ""),
        alert_thresholds=tuple(raw.get("alert_thresholds", ())),
    )
    print(render_slo_doc(definition), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sre_toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("budget", help="error-budget math for one SLO window")
    p.add_argument("--slo", type=float, required=True, help="SLO as a fraction, e.g. 0.999")
    p.add_argument("--total", type=int, required=True, help="total events in the window")
    p.add_argument("--bad", type=int, required=True, help="bad events in the window")
    p.add_argument("--window-days", type=float, default=None,
                   help="SLO window length; adds an exhaustion projection")
    p.set_defaults(func=_cmd_budget)

    p = sub.add_parser("downtime", help="allowed downtime minutes for an SLO")
    p.add_argument("--slo", type=float, required=True)
    p.add_argument("--days", type=float, default=None,
                   help="window length in days; omit for a 1/7/30/90-day table")
    p.set_defaults(func=_cmd_downtime)

    p = sub.add_parser("triage", help="classify alerts from a JSON file ('-' for stdin)")
    p.add_argument("file")
    p.add_argument("--by-service", action="store_true",
                   help="group output by service with counts and worst severity")
    p.add_argument("--json", action="store_true", help="emit the triaged alerts as JSON")
    p.add_argument("--inhibit", action="store_true",
                   help="suppress lower-severity alerts on services with an active critical")
    p.set_defaults(func=_cmd_triage)

    p = sub.add_parser("report", help="Markdown SLO status report from a JSON file ('-' for stdin)")
    p.add_argument("file")
    p.set_defaults(func=_cmd_report)

    p = sub.add_parser("burn", help="evaluate multi-window burn-rate rules from a JSON file ('-' for stdin)")
    p.add_argument("file")
    p.add_argument("--json", action="store_true", help="emit the firing rules as JSON")
    p.set_defaults(func=_cmd_burn)

    p = sub.add_parser("postmortem", help="render a Markdown postmortem from a JSON incident ('-' for stdin)")
    p.add_argument("file")
    p.set_defaults(func=_cmd_postmortem)

    p = sub.add_parser("metrics", help="aggregate TTD/TTR across a JSON list of incidents ('-' for stdin)")
    p.add_argument("file")
    p.set_defaults(func=_cmd_metrics)

    p = sub.add_parser("slo-doc", help="render a Markdown SLO definition from a JSON spec ('-' for stdin)")
    p.add_argument("file")
    p.set_defaults(func=_cmd_slo_doc)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
