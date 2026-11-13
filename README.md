# sre-toolkit

[![CI](https://github.com/midya8/sre-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/midya8/sre-toolkit/actions/workflows/ci.yml)

A small set of Python utilities for the SRE work that kept coming up: error-budget math, alert triage, and postmortems. Standard library only, so there's nothing to install — it runs anywhere Python 3.10+ does.

## Commands

| Task | Command | Output and exit status |
|---|---|---|
| Check an error budget | `budget`, `downtime` | Budget consumed, burn rate and allowed downtime; `budget` exits 1 when exhausted |
| Sort an alert list | `triage` | Keyword severity, deduplicated occurrence counts, optional silences, inhibition and team routing |
| Review SLO snapshots | `report` | Markdown or JSON, optional fleet summary and worst-first sorting; exits 1 if any budget is exhausted |
| Evaluate burn rules | `burn` | Rules firing on both supplied long and short windows; optional policy template or time-series replay |
| Write an incident record | `postmortem` | Markdown or JSON with timestamp-derived response metrics |
| Aggregate incident records | `metrics` | Mean, median and nearest-rank p90 TTD/TTR; optional severity, service or ISO-week breakdowns |
| Write an SLO definition | `slo-doc` | Markdown or JSON describing the target, window, SLI and alerting policy |

Triage is keyword-based out of the box, but `triage --rules` lets you swap in your own vocabulary. `--silences` doesn't delete matched alerts — it moves them into a visible section with the reason attached. `--routes` assigns owners, and `--by-owner` rolls the result up by team. When a service already has a critical alert open, inhibition quiets the lower-severity symptoms underneath it. One thing to be clear about: this classifies the records you hand it. It doesn't tell you what caused the incident.

The default burn rules page at 14.4x over 1h and 5m, and open a ticket at 6x over 6h and 30m — both windows have to cross the threshold before anything fires. That filters out a lot of short spikes, though a sharp enough one can still page. `burn --suggest` scales a three-tier policy template to your SLO window, and `burn --replay` walks a time series and reports the firing intervals at each bucket tick, exiting 1 if any critical rule fired. It works off the samples you give it, not a live monitoring feed.

`metrics --action-items` lists the open actions with days since resolution, and exits 1 if a resolved incident older than `--stale-days` (default 14) still has open items. Records without a parseable timestamp just get skipped from the response-time aggregates. And the exhaustion projection in `report` is a straight-line extrapolation — it assumes the current burn rate continues, so don't read it as a forecast.

## Usage

Library:

```python
from sre_toolkit.error_budget import compute_error_budget, allowed_downtime_minutes
from sre_toolkit.alert_triage import Alert, triage
from sre_toolkit.postmortem import Incident, render_postmortem

budget = compute_error_budget(slo=0.999, total_events=10_000, bad_events=5)
print(f"budget consumed: {budget.consumed_fraction:.1%}, burn rate: {budget.burn_rate:.2f}x")

print(f"99.9% over 30 days allows {allowed_downtime_minutes(0.999, 30):.1f} minutes down")

alerts = triage([
    Alert("a1", "web", "Weekly report ready"),
    Alert("a2", "api", "Service down"),
    Alert("a3", "db", "Error rate elevated"),
])
for a in alerts:
    print(a.severity, a.service, a.summary)
```

CLI:

```bash
python -m sre_toolkit budget --slo 0.999 --total 10000 --bad 5 --window-days 30
python -m sre_toolkit downtime --slo 0.999          # 1/7/30/90-day table
python -m sre_toolkit downtime --slo 0.999 --days 30
python -m sre_toolkit triage examples/alerts.json
python -m sre_toolkit triage examples/alerts.json --top-talkers   # noisiest deduped alerts first
python -m sre_toolkit triage examples/alerts.json --by-severity   # active alerts per severity
python -m sre_toolkit triage examples/alerts.json --silences examples/silences.json
python -m sre_toolkit triage examples/alerts.json --routes examples/routes.json --by-owner  # per-team roll-up
python -m sre_toolkit report examples/slo-snapshots.json
python -m sre_toolkit report examples/slo-snapshots.json --summary  # fleet roll-up: status counts, worst SLO
python -m sre_toolkit burn examples/burn-samples.json      # exit 1 when a critical rule fires
python -m sre_toolkit burn examples/burn-replay.json --replay  # firing intervals over a time series
python -m sre_toolkit burn --suggest --slo 0.999           # policy template for your SLO
python -m sre_toolkit postmortem examples/incident.json
python -m sre_toolkit metrics examples/incidents.json
python -m sre_toolkit metrics examples/incidents.json --by-service  # TTD/TTR per affected service
python -m sre_toolkit metrics examples/incidents.json --action-items  # open action items, exit 1 when stale
python -m sre_toolkit slo-doc examples/slo-definition.json
python -m sre_toolkit slo-doc examples/slo-definition.json --json   # machine-readable definition
```

## Tests

```bash
python -m unittest discover -s tests -v
```

254 tests cover the budget math (including boundary and validation cases), severity classification, dedupe, ordering, grouping, severity and noise roll-ups, silence validation, matching and expiry, alert ownership routing and roll-ups, burn-rate rules, policy suggestion and time-series replay, postmortem rendering, report rendering with fleet summaries, SLO document rendering (Markdown and JSON), metrics aggregation (per severity, per service, per week), action-item follow-through, and the CLI commands.

## Layout

```
sre_toolkit/
  error_budget.py   # SLO budget, burn rate, downtime, exhaustion projection
  alert_triage.py   # severity rules, dedupe, severity ordering, grouping, owner routing
  silences.py       # bounded alert silences with matchers, reasons, expiry
  postmortem.py     # structured incident -> Markdown postmortem
  burn_alerts.py    # multi-window burn-rate alerting rules
  report.py         # Markdown SLO status report from window snapshots
  slo_doc.py        # SLO definition documents (Markdown + JSON payload)
  __main__.py       # CLI: budget / downtime / triage / report / burn / postmortem / slo-doc
tests/              # unittest suite, no external dependencies
examples/           # sample alert input for the CLI
```
