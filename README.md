# sre-toolkit

[![CI](https://github.com/midya8/sre-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/midya8/sre-toolkit/actions/workflows/ci.yml)

Small, dependency-free Python utilities for day-to-day SRE work: error-budget
math, alert triage, and postmortem generation. Standard library only - no
`pip install` needed, works anywhere Python 3.10+ runs.

## Why

The math and the documents are the boring parts of incident work that still
need to be right. This toolkit makes them scriptable:

- **Error budgets** - compute budget fraction, consumed share, burn rate and
  allowed downtime for an SLO, with input validation instead of silent garbage.
  `budget` exits 1 when the budget is exhausted (a scriptable health gate)
  and both `budget` and `downtime` emit `--json` for pipelines.
- **Alert triage** - classify alerts by keyword rules, dedupe repeats while
  keeping each distinct alert's fire count (`(x12)` in the CLI, `occurrences`
  in JSON), sort by severity so the page-worthy problem is on top, and
  `--inhibit` suppresses lower-severity symptoms on a service with an active
  critical, the way Alertmanager inhibit rules keep a known outage from
  paging for every symptom. `--rules rules.json` swaps the built-in
  keywords for a team's own vocabulary (a JSON object mapping severity to
  keywords).
- **Postmortems** - render a consistent Markdown postmortem from structured
  incident data, with timeline, action-item checklists, and response metrics
  (time to detect, time to resolve, total duration) computed automatically
  from the incident timestamps when they are parseable. The `metrics` CLI
  aggregates TTD and TTR across a list of incidents for MTTR tracking -
  mean, median and nearest-rank p90 - skipping incidents without parseable
  timestamps, with `--json` for dashboards.
- **Burn-rate alerts** - multi-window alerting (page at 14.4x over 1h+5m,
  ticket at 6x over 6h+30m) that only fires when burn is elevated on both the
  long and short window, so blips never page anyone. The `burn` CLI accepts
  custom rules in its JSON spec when the defaults do not fit a service, and
  emits the firing rules as JSON (`--json`) for paging pipelines.
- **Status reports** - render a Markdown SLO status report (table plus
  plain-language status lines) from a JSON list of SLO window snapshots;
  snapshots carrying their `window_days` also get an exhaustion projection
  ("budget exhausts in ~3.0 days at current burn"). Exits 1 when any budget
  is exhausted, so it can gate a cron job or CI pipeline, and `--json`
  emits the same per-SLO detail for dashboards and tooling.
- **SLO documents** - render an SLO definition (target, window, SLI, error
  budget, alerting policy) as Markdown, so objectives live reviewably in
  the repo next to the service they cover.

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
python -m sre_toolkit report examples/slo-snapshots.json
python -m sre_toolkit burn examples/burn-samples.json      # exit 1 when a critical rule fires
python -m sre_toolkit postmortem examples/incident.json
python -m sre_toolkit metrics examples/incidents.json
python -m sre_toolkit slo-doc examples/slo-definition.json
```

## Tests

```bash
python -m unittest discover -s tests -v
```

78 tests cover the budget math (including boundary and validation cases),
severity classification, dedupe, ordering, grouping, burn-rate rules,
postmortem rendering, report rendering, and the CLI commands.

## Layout

```
sre_toolkit/
  error_budget.py   # SLO budget, burn rate, downtime, exhaustion projection
  alert_triage.py   # severity rules, dedupe, severity ordering, grouping
  postmortem.py     # structured incident -> Markdown postmortem
  burn_alerts.py    # multi-window burn-rate alerting rules
  report.py         # Markdown SLO status report from window snapshots
  slo_doc.py        # Markdown SLO definition documents
  __main__.py       # CLI: budget / downtime / triage / report / burn / postmortem / slo-doc
tests/              # unittest suite, no external dependencies
examples/           # sample alert input for the CLI
```
