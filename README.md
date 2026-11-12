# sre-toolkit

[![CI](https://github.com/midya8/sre-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/midya8/sre-toolkit/actions/workflows/ci.yml)

Small, dependency-free Python utilities for day-to-day SRE work: error-budget
math, alert triage, and postmortem generation. Standard library only - no
`pip install` needed, works anywhere Python 3.10+ runs.

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

`triage --rules` replaces the built-in keyword vocabulary. `--silences` keeps
matched alerts in a visible section with a reason, rather than deleting them.
`--routes` assigns owners; `--by-owner` groups the result by team. Inhibition
suppresses lower-severity symptoms on a service with an active critical alert.
These rules classify supplied records; they do not establish an incident's cause.

The default burn rules use 14.4x over 1h and 5m for a page, and 6x over 6h and
30m for a ticket. Both windows must meet the threshold. This reduces sensitivity
to some short spikes, but is not a guarantee that a short spike cannot page.
`burn --suggest` scales a three-tier template to the SLO window. `burn --replay`
reports firing intervals at bucket ticks and exits 1 if any critical rule fired.
It evaluates supplied samples, not a live monitoring service.

`metrics --action-items` lists open actions with days since resolution. It exits
1 when a resolved incident older than `--stale-days` (default 14) still has open
items. Records without parseable timestamps are skipped for response-time
aggregates. An exhaustion projection in `report` assumes the current burn rate
continues; it is not a forecast.

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

254 tests cover the budget math (including boundary and validation cases),
severity classification, dedupe, ordering, grouping, severity and noise
roll-ups, silence validation, matching and expiry, alert ownership routing and roll-ups, burn-rate rules, policy suggestion and
time-series replay,
postmortem rendering, report rendering with fleet summaries, SLO document
rendering (Markdown and JSON), metrics aggregation (per severity, per
service, per week), action-item follow-through, and the CLI commands.

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
