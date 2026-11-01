"""Command-line entry point: ``python -m sre_toolkit``.

Subcommands:
    budget      error-budget math for one SLO window
    downtime    allowed downtime in minutes for an SLO over N days
    triage      classify a JSON list of alerts
    report      render a Markdown SLO status report from a JSON list
"""

from __future__ import annotations

import argparse
import json
import sys

from .alert_triage import Alert, triage
from .error_budget import allowed_downtime_minutes, compute_error_budget
from .report import SLOSnapshot, render_report


def _cmd_budget(args: argparse.Namespace) -> int:
    budget = compute_error_budget(args.slo, args.total, args.bad)
    print(f"SLO target:        {budget.slo:.4%}")
    print(f"Budget fraction:   {budget.budget_fraction:.4%}")
    print(f"Consumed:          {budget.consumed_fraction:.1%}")
    print(f"Remaining:         {budget.remaining_fraction:.1%}")
    print(f"Burn rate:         {budget.burn_rate:.2f}x")
    return 0 if budget.remaining_fraction > 0 else 1


def _cmd_downtime(args: argparse.Namespace) -> int:
    minutes = allowed_downtime_minutes(args.slo, args.days)
    print(f"Allowed downtime: {minutes:.1f} minutes over {args.days:g} days")
    return 0


def _cmd_triage(args: argparse.Namespace) -> int:
    raw = json.load(sys.stdin if args.file == "-" else open(args.file))
    alerts = [Alert(**item) for item in raw]
    for alert in triage(alerts):
        print(f"[{alert.severity:8s}] {alert.service:20s} {alert.summary}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    raw = json.load(sys.stdin if args.file == "-" else open(args.file))
    snapshots = [
        SLOSnapshot(
            name=item["name"],
            slo=float(item["slo"]),
            total_events=int(item["total"]),
            bad_events=int(item["bad"]),
        )
        for item in raw
    ]
    print(render_report(snapshots), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sre_toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("budget", help="error-budget math for one SLO window")
    p.add_argument("--slo", type=float, required=True, help="SLO as a fraction, e.g. 0.999")
    p.add_argument("--total", type=int, required=True, help="total events in the window")
    p.add_argument("--bad", type=int, required=True, help="bad events in the window")
    p.set_defaults(func=_cmd_budget)

    p = sub.add_parser("downtime", help="allowed downtime minutes for an SLO")
    p.add_argument("--slo", type=float, required=True)
    p.add_argument("--days", type=float, required=True)
    p.set_defaults(func=_cmd_downtime)

    p = sub.add_parser("triage", help="classify alerts from a JSON file ('-' for stdin)")
    p.add_argument("file")
    p.set_defaults(func=_cmd_triage)

    p = sub.add_parser("report", help="Markdown SLO status report from a JSON file ('-' for stdin)")
    p.add_argument("file")
    p.set_defaults(func=_cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
