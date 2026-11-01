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

from .silences import apply_silences, load_silences
from .alert_triage import (Alert, dedupe_key, duplicate_counts, group_by_service,
                           inhibit_by_critical, load_routes, owner_rollup,
                           route_owner, rules_from_dict, severity_counts,
                           top_talkers, triage)
from .burn_alerts import (DEFAULT_RULES, BurnRule, BurnSample,
                          evaluate_rules, replay_rules, suggest_rules)
from .error_budget import (
    allowed_downtime_minutes,
    compute_error_budget,
    time_to_exhaustion_days,
)
from .postmortem import (Incident, _format_duration, render_postmortem, response_metrics,
                         action_item_followup, format_action_item_followup,
                         summarize_by_severity, summarize_by_service, summarize_by_week,
                         summarize_incidents)
from .report import (SLOSnapshot, consumed_fraction, fleet_summary, render_report,
                     snapshot_summary)
from .slo_doc import SLODefinition, render_slo_doc, slo_doc_payload


def _cmd_budget(args: argparse.Namespace) -> int:
    budget = compute_error_budget(args.slo, args.total, args.bad)
    if args.json:
        payload = {
            "slo": budget.slo,
            "total_events": budget.total_events,
            "bad_events": budget.bad_events,
            "budget_fraction": budget.budget_fraction,
            "consumed_fraction": budget.consumed_fraction,
            "burn_rate": budget.burn_rate,
            "remaining_fraction": budget.remaining_fraction,
            "allowed_bad_events": budget.allowed_bad_events,
            "remaining_bad_events": budget.remaining_bad_events,
            "budget_exhausted": budget.remaining_fraction <= 0,
        }
        if args.window_days is not None:
            days = time_to_exhaustion_days(budget, args.window_days)
            payload["window_days"] = args.window_days
            payload["exhaustion_days"] = None if days is None or days <= 0 else days
        print(json.dumps(payload, indent=2))
        return 0 if budget.remaining_fraction > 0 else 1
    print(f"SLO target:        {budget.slo:.4%}")
    print(f"Budget fraction:   {budget.budget_fraction:.4%}")
    print(f"Consumed:          {budget.consumed_fraction:.1%}")
    print(f"Remaining:         {budget.remaining_fraction:.1%}")
    print(f"Burn rate:         {budget.burn_rate:.2f}x")
    print(f"Bad events:        {budget.bad_events} of {budget.allowed_bad_events} allowed "
          f"({budget.remaining_bad_events} left)")
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
        if args.json:
            print(json.dumps({"slo": args.slo, "window_days": args.days,
                              "allowed_downtime_minutes": minutes}, indent=2))
        else:
            print(f"Allowed downtime: {minutes:.1f} minutes over {args.days:g} days")
        return 0
    if args.json:
        print(json.dumps({"slo": args.slo, "allowed_downtime_minutes": {
            str(window): allowed_downtime_minutes(args.slo, window)
            for window in (1, 7, 30, 90)
        }}, indent=2))
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
    rules = None
    if args.rules:
        try:
            rules = rules_from_dict(json.load(open(args.rules)))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"error: bad rules file: {exc}", file=sys.stderr)
            return 2
    alerts = triage(incoming, rules=rules) if rules else triage(incoming)
    silenced: list = []
    if args.silences:
        try:
            silence_list = load_silences(json.load(open(args.silences)))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"error: bad silences file: {exc}", file=sys.stderr)
            return 2
        alerts, silenced = apply_silences(alerts, silence_list)
    inhibited: list[Alert] = []
    if args.inhibit:
        alerts, inhibited = inhibit_by_critical(alerts)
    routes = None
    if args.routes:
        try:
            routes = load_routes(json.load(open(args.routes)))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"error: bad routes file: {exc}", file=sys.stderr)
            return 2
    if args.by_owner and routes is None:
        print("error: --by-owner requires --routes FILE", file=sys.stderr)
        return 2

    def _owner(alert: Alert) -> str:
        return f" -> {route_owner(routes, alert.service)}" if routes else ""

    def _suffix(alert: Alert) -> str:
        n = counts[dedupe_key(alert)]
        return f" (x{n})" if n > 1 else ""

    if args.json:
        payload = {"alerts": [
            {"alert_id": a.alert_id, "service": a.service,
             "summary": a.summary, "severity": a.severity,
             "occurrences": counts[dedupe_key(a)],
             **({"owner": route_owner(routes, a.service)} if routes else {})}
            for a in alerts
        ]}
        if args.by_owner:
            payload["by_owner"] = owner_rollup(alerts, routes)
        if args.by_severity:
            payload["by_severity"] = severity_counts(alerts)
        if args.top_talkers:
            payload["top_talkers"] = [
                {"alert_id": a.alert_id, "service": a.service,
                 "summary": a.summary, "severity": a.severity,
                 "occurrences": n}
                for a, n in (top_talkers(incoming, rules=rules) if rules
                             else top_talkers(incoming))
            ]
        if silenced:
            payload["silenced"] = [
                {"alert_id": a.alert_id, "service": a.service,
                 "summary": a.summary, "severity": a.severity,
                 "occurrences": counts[dedupe_key(a)],
                 "silenced_reason": silence.reason}
                for a, silence in silenced
            ]
        if args.inhibit:
            payload["inhibited"] = [
                {"alert_id": a.alert_id, "service": a.service,
                 "summary": a.summary, "severity": a.severity,
                 "occurrences": counts[dedupe_key(a)]}
                for a in inhibited
            ]
            print(json.dumps(payload, indent=2))
        elif args.top_talkers or args.by_severity or silenced or args.by_owner:
            print(json.dumps(payload, indent=2))
        else:
            print(json.dumps(payload["alerts"], indent=2))
        return 0
    if args.by_owner:
        print("Owners (worst severity first):")
        for row in owner_rollup(alerts, routes):
            breakdown = ", ".join(f"{n} {sev}" for sev, n in
                                  sorted(row["by_severity"].items()))
            print(f"  {row['owner']:20s} {row['alerts']:>3} alert"
                  f"{'s' if row['alerts'] != 1 else ''} ({breakdown})")
        return 0
    if args.by_service:
        for service, group in sorted(group_by_service(alerts).items()):
            worst = group[0].severity  # triage() sorts most severe first
            n = len(group)
            print(f"{service} ({n} alert{'' if n == 1 else 's'}, worst: {worst})")
            for alert in group:
                print(f"  [{alert.severity:8s}] {alert.summary}{_suffix(alert)}")
        return 0
    if args.by_severity:
        counts = severity_counts(alerts)
        print("Severity counts:",
              ", ".join(f"{sev} {n}" for sev, n in counts.items()) or "none")
        if args.inhibit and inhibited:
            print(f"({len(inhibited)} inhibited not counted)")
        if silenced:
            print(f"({len(silenced)} silenced not counted)")
        return 0
    if args.top_talkers:
        print("Top talkers (deduped, by occurrences):")
        for alert, n in (top_talkers(incoming, rules=rules) if rules
                         else top_talkers(incoming)):
            print(f"  {n:>4}x [{alert.severity:8s}] {alert.service}: {alert.summary}")
        return 0
    for alert in alerts:
        print(f"[{alert.severity:8s}] {alert.service:20s} {alert.summary}{_suffix(alert)}"
              f"{_owner(alert)}")
    if inhibited:
        print(f"({len(inhibited)} alert{'' if len(inhibited) == 1 else 's'} "
              f"inhibited: symptoms of a critical on the same service)")
        for alert in inhibited:
            print(f"  [{alert.severity:8s}] {alert.service:20s} {alert.summary}{_suffix(alert)}")
    if silenced:
        print(f"({len(silenced)} alert{'' if len(silenced) == 1 else 's'} silenced)")
        for alert, silence in silenced:
            print(f"  [{alert.severity:8s}] {alert.service:20s} {alert.summary}{_suffix(alert)}"
                  f" - silenced: {silence.reason}")
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
    exhausted = any(
        snap.total_events > 0
        and compute_error_budget(snap.slo, snap.total_events, snap.bad_events).remaining_fraction <= 0
        for snap in snapshots
    )
    if args.worst_first:
        snapshots.sort(key=consumed_fraction, reverse=True)
    if args.json:
        payload = {
            "slos": [snapshot_summary(snap) for snap in snapshots],
            "exhausted": exhausted,
        }
        if args.summary:
            payload["fleet_summary"] = fleet_summary(snapshots)
        print(json.dumps(payload, indent=2))
    else:
        print(render_report(snapshots, include_summary=args.summary), end="")
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
    if args.suggest:
        try:
            suggested = suggest_rules(args.slo, args.window_days)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({
            "slo": args.slo,
            "window_days": args.window_days,
            "samples": [],
            "rules": [
                {"name": r.name, "severity": r.severity,
                 "burn_threshold": r.burn_threshold,
                 "long_window_hours": r.long_window_hours,
                 "short_window_hours": r.short_window_hours}
                for r in suggested
            ],
        }, indent=2))
        return 0
    if not args.file:
        print("error: burn needs a JSON samples file, or --suggest to emit a "
              "policy template", file=sys.stderr)
        return 2
    raw = json.load(sys.stdin if args.file == "-" else open(args.file))
    if args.replay:
        return _burn_replay(args, raw)
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


def _burn_replay(args: argparse.Namespace, raw: dict) -> int:
    """burn --replay: run a timestamped series through the rules."""
    try:
        rules = _burn_rules(raw.get("rules"))
        reports = replay_rules(float(raw["slo"]), raw.get("buckets", []),
                               rules=rules if rules is not None else DEFAULT_RULES)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    any_critical = any(r["firing_ticks"] and r["severity"] == "critical"
                       for r in reports)
    if args.json:
        print(json.dumps({
            "slo": float(raw["slo"]),
            "buckets": len(raw["buckets"]),
            "rules": [
                {**{k: v for k, v in r.items() if k != "intervals"},
                 "intervals": [
                     {**iv,
                      "start": iv["start"].isoformat(),
                      "end": iv["end"].isoformat()}
                     for iv in r["intervals"]
                 ]}
                for r in reports
            ],
        }, indent=2))
        return 1 if any_critical else 0
    print(f"Replay over {len(raw['buckets'])} buckets:")
    for r in reports:
        if not r["intervals"]:
            print(f"[{r['severity']:8s}] {r['name']}: never fired")
            continue
        for iv in r["intervals"]:
            print(f"[{r['severity']:8s}] {r['name']}: fired "
                  f"{iv['start'].isoformat()} -> {iv['end'].isoformat()} "
                  f"({iv['ticks']} tick{'s' if iv['ticks'] != 1 else ''})")
    return 1 if any_critical else 0


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
    incident = _incident_from(raw)
    if args.json:
        metrics = response_metrics(incident)
        print(json.dumps({
            "title": incident.title,
            "severity": incident.severity,
            "time_to_detect_minutes": _minutes(metrics.time_to_detect) if metrics else None,
            "time_to_resolve_minutes": _minutes(metrics.time_to_resolve) if metrics else None,
            "total_duration_minutes": _minutes(metrics.total_duration) if metrics else None,
        }, indent=2))
        return 0
    print(render_postmortem(incident), end="")
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    raw = json.load(sys.stdin if args.file == "-" else open(args.file))
    incidents = [_incident_from(item) for item in raw]
    followup = None
    if args.action_items:
        try:
            followup = action_item_followup(raw, stale_days=args.stale_days)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    stats = summarize_incidents(incidents)
    if stats is None and followup is None:
        print("error: no incidents with computable response metrics", file=sys.stderr)
        return 2
    if args.json:
        summary = _metrics_summary(stats, incidents)
        if args.by_service:
            summary["by_service"] = {
                service: {
                    "incidents": group.incidents,
                    "mean_time_to_detect_minutes": _minutes(group.mean_time_to_detect),
                    "mean_time_to_resolve_minutes": _minutes(group.mean_time_to_resolve),
                }
                for service, group in sorted(summarize_by_service(incidents).items())
            }
        if args.by_week:
            summary["by_week"] = [
                {"week": label,
                 "incidents": group.incidents,
                 "mean_time_to_detect_minutes": _minutes(group.mean_time_to_detect),
                 "mean_time_to_resolve_minutes": _minutes(group.mean_time_to_resolve)}
                for label, group in summarize_by_week(incidents)
            ]
        if followup is not None:
            summary["action_items"] = followup
        print(json.dumps(summary, indent=2))
        return 1 if (followup is not None and followup["stale_incidents"]) else 0
    if stats is None:
        print("No incidents with parseable timestamps.")
        print(format_action_item_followup(followup))
        return 1 if followup["stale_incidents"] else 0
    skipped = f" ({stats.skipped} skipped, timestamps unparseable)" if stats.skipped else ""
    print(f"Incidents analyzed: {stats.incidents}{skipped}")
    print(f"Time to detect:  mean {_format_duration(stats.mean_time_to_detect)}, "
          f"median {_format_duration(stats.median_time_to_detect)}, "
          f"p90 {_format_duration(stats.p90_time_to_detect)}")
    print(f"Time to resolve: mean {_format_duration(stats.mean_time_to_resolve)}, "
          f"median {_format_duration(stats.median_time_to_resolve)}, "
          f"p90 {_format_duration(stats.p90_time_to_resolve)}")
    by_severity = summarize_by_severity(incidents)
    if len(by_severity) > 1:
        print("By severity:")
        for severity, group in sorted(by_severity.items()):
            print(f"  {severity}: n={group.incidents}, "
                  f"mean TTD {_format_duration(group.mean_time_to_detect)}, "
                  f"mean TTR {_format_duration(group.mean_time_to_resolve)}")
    if args.by_service:
        by_service = summarize_by_service(incidents)
        if by_service:
            print("By service:")
            for service, group in sorted(by_service.items()):
                print(f"  {service}: n={group.incidents}, "
                      f"mean TTD {_format_duration(group.mean_time_to_detect)}, "
                      f"mean TTR {_format_duration(group.mean_time_to_resolve)}")
    if args.by_week:
        weekly = summarize_by_week(incidents)
        if weekly:
            print("By week:")
            for label, group in weekly:
                print(f"  {label}: n={group.incidents}, "
                      f"mean TTD {_format_duration(group.mean_time_to_detect)}, "
                      f"mean TTR {_format_duration(group.mean_time_to_resolve)}")
    if followup is not None:
        print()
        print(format_action_item_followup(followup))
        return 1 if followup["stale_incidents"] else 0
    return 0


def _minutes(delta) -> float:
    return round(delta.total_seconds() / 60, 2)


def _metrics_summary(stats, incidents=None) -> dict:
    """Machine-readable incident metrics - durations in minutes.

    With the incidents, adds a per-severity breakdown - MTTR only means
    something split by severity.
    """
    summary = {
        "incidents": stats.incidents,
        "skipped": stats.skipped,
        "time_to_detect_minutes": {
            "mean": _minutes(stats.mean_time_to_detect),
            "median": _minutes(stats.median_time_to_detect),
            "p90": _minutes(stats.p90_time_to_detect),
        },
        "time_to_resolve_minutes": {
            "mean": _minutes(stats.mean_time_to_resolve),
            "median": _minutes(stats.median_time_to_resolve),
            "p90": _minutes(stats.p90_time_to_resolve),
        },
    }
    if incidents is not None:
        summary["by_severity"] = {
            severity: {
                "incidents": group.incidents,
                "mean_time_to_detect_minutes": _minutes(group.mean_time_to_detect),
                "mean_time_to_resolve_minutes": _minutes(group.mean_time_to_resolve),
            }
            for severity, group in sorted(summarize_by_severity(incidents).items())
        }
    return summary


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
    if args.json:
        print(json.dumps(slo_doc_payload(definition), indent=2))
    else:
        print(render_slo_doc(definition), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sre_toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("budget", help="error-budget math for one SLO window")
    p.add_argument("--slo", type=float, required=True, help="SLO as a fraction, e.g. 0.999")
    p.add_argument("--total", type=int, required=True, help="total events in the window")
    p.add_argument("--bad", type=int, required=True, help="bad events in the window")
    p.add_argument("--json", action="store_true", help="emit the budget as JSON")
    p.add_argument("--window-days", type=float, default=None,
                   help="SLO window length; adds an exhaustion projection")
    p.set_defaults(func=_cmd_budget)

    p = sub.add_parser("downtime", help="allowed downtime minutes for an SLO")
    p.add_argument("--slo", type=float, required=True)
    p.add_argument("--days", type=float, default=None,
                   help="window length in days; omit for a 1/7/30/90-day table")
    p.add_argument("--json", action="store_true", help="emit allowed downtime as JSON")
    p.set_defaults(func=_cmd_downtime)

    p = sub.add_parser("triage", help="classify alerts from a JSON file ('-' for stdin)")
    p.add_argument("file")
    p.add_argument("--rules", metavar="FILE",
                   help="custom severity rules: JSON object mapping severity to keywords")
    p.add_argument("--action-items", action="store_true",
                   help="follow-through report: open action items per incident; "
                        "exits 1 when any incident resolved > --stale-days ago still has open items")
    p.add_argument("--stale-days", type=float, default=14.0,
                   help="with --action-items: days after resolution before open items go stale")
    p.add_argument("--by-service", action="store_true",
                   help="group output by service with counts and worst severity")
    p.add_argument("--top-talkers", action="store_true",
                   help="rank deduped alerts by occurrence count, noisiest first")
    p.add_argument("--by-severity", action="store_true",
                   help="print deduped alert counts per severity and exit")
    p.add_argument("--json", action="store_true", help="emit the triaged alerts as JSON")
    p.add_argument("--inhibit", action="store_true",
                   help="suppress lower-severity alerts on services with an active critical")
    p.add_argument("--routes", metavar="FILE",
                   help="JSON service->owner map with a default owner; "
                        "annotates each alert with its owner")
    p.add_argument("--by-owner", action="store_true",
                   help="per-owner roll-up (worst severity first); requires --routes")
    p.add_argument("--silences", metavar="FILE",
                   help="silence file: JSON list of {service?, severity?, contains?, "
                        "reason, until}; matching alerts move to a silenced section")
    p.set_defaults(func=_cmd_triage)

    p = sub.add_parser("report", help="Markdown SLO status report from a JSON file ('-' for stdin)")
    p.add_argument("file")
    p.add_argument("--summary", action="store_true",
                   help="append a fleet roll-up (counts per status class, worst SLO)")
    p.add_argument("--json", action="store_true",
                   help="emit per-SLO budget details as JSON instead of Markdown")
    p.add_argument("--worst-first", action="store_true",
                   help="sort SLOs by budget consumed, most consumed first")
    p.set_defaults(func=_cmd_report)

    p = sub.add_parser("burn", help="evaluate multi-window burn-rate rules from a JSON file ('-' for stdin)")
    p.add_argument("file", nargs="?", help="JSON samples file; omit with --suggest")
    p.add_argument("--json", action="store_true", help="emit the firing rules as JSON")
    p.add_argument("--suggest", action="store_true",
                   help="emit a standard three-tier burn-rate policy template for "
                        "--slo/--window-days instead of evaluating samples")
    p.add_argument("--slo", type=float, default=0.999,
                   help="with --suggest: the SLO the policy protects (default 0.999)")
    p.add_argument("--window-days", type=float, default=30.0,
                   help="with --suggest: the SLO window the policy covers (default 30)")
    p.add_argument("--replay", action="store_true",
                   help="treat the file as a time series of timestamped buckets and "
                        "replay the rules over it, reporting each rule's firing intervals")
    p.set_defaults(func=_cmd_burn)

    p = sub.add_parser("postmortem", help="render a Markdown postmortem from a JSON incident ('-' for stdin)")
    p.add_argument("file")
    p.add_argument("--json", action="store_true",
                   help="emit the response metrics as JSON (durations in minutes)")
    p.set_defaults(func=_cmd_postmortem)

    p = sub.add_parser("metrics", help="aggregate TTD/TTR across a JSON list of incidents ('-' for stdin)")
    p.add_argument("file")
    p.add_argument("--by-week", action="store_true",
                   help="also bucket the aggregates by ISO week of resolution (trend view)")
    p.add_argument("--action-items", action="store_true",
                   help="follow-through report: open action items per incident; "
                        "exits 1 when any incident resolved > --stale-days ago still has open items")
    p.add_argument("--stale-days", type=float, default=14.0,
                   help="with --action-items: days after resolution before open items go stale")
    p.add_argument("--by-service", action="store_true",
                   help="also aggregate per affected service (incidents count toward each service they list)")
    p.add_argument("--json", action="store_true",
                   help="emit the aggregates as JSON (durations in minutes)")
    p.set_defaults(func=_cmd_metrics)

    p = sub.add_parser("slo-doc", help="render a Markdown SLO definition from a JSON spec ('-' for stdin)")
    p.add_argument("file")
    p.add_argument("--json", action="store_true",
                   help="emit the definition and derived error budget as JSON instead of Markdown")
    p.set_defaults(func=_cmd_slo_doc)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
