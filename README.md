# sre-toolkit

[![CI](https://github.com/midya8/sre-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/midya8/sre-toolkit/actions/workflows/ci.yml)

Small, dependency-free Python utilities for day-to-day SRE work: error-budget
math, alert triage, and postmortem generation. Standard library only - no
`pip install` needed, works anywhere Python 3.10+ runs.

## Why

The math and the documents are the boring parts of incident work that still
need to be right. This toolkit makes them scriptable:

- **Error budgets** - compute budget fraction, consumed share, burn rate,
  allowed downtime, and how many bad events the window still affords
  ("5 of 10 allowed") for an SLO, with input validation instead of silent
  garbage.
  `budget` exits 1 when the budget is exhausted (a scriptable health gate)
  and both `budget` and `downtime` emit `--json` for pipelines.
- **Alert triage** - classify alerts by keyword rules, dedupe repeats while
  keeping each distinct alert's fire count (`(x12)` in the CLI, `occurrences`
  in JSON), sort by severity so the page-worthy problem is on top, and
  `--inhibit` suppresses lower-severity symptoms on a service with an active
  critical, the way Alertmanager inhibit rules keep a known outage from
  paging for every symptom. `--rules rules.json` swaps the built-in
  keywords for a team's own vocabulary (a JSON object mapping severity to
  keywords), and `--silences silences.json` applies Alertmanager-style
  silences - bounded, reasoned suppressions matched on service, severity
  and/or summary substring - moving matched alerts into a visible
  silenced section (with the reason) instead of the main list.
- **Postmortems** - render a consistent Markdown postmortem from structured
  incident data, with timeline, action-item checklists, and response metrics
  (time to detect, time to resolve, total duration) computed automatically
  from the incident timestamps when they are parseable, also available as
  `--json` for pipelines. The `metrics` CLI
  aggregates TTD and TTR across a list of incidents for MTTR tracking -
  mean, median and nearest-rank p90, with a per-severity breakdown because
  MTTR only means something split by severity - skipping incidents without
  parseable timestamps, with `--json` for dashboards. `--by-week` buckets
  the same aggregates by ISO week of resolution, answering "are we getting
  faster?" as a trend instead of one flat number. `metrics --action-items`
  adds a follow-through report: incidents list `action_items` (plain strings
  or `{"item": ..., "done": true}` objects), and the report groups open items
  per incident with days since resolution, exits 1 when any incident resolved
  more than `--stale-days` (default 14) ago still has open items, and surfaces
  the same data as an `action_items` block in `--json`.
- **Burn-rate alerts** - multi-window alerting (page at 14.4x over 1h+5m,
  ticket at 6x over 6h+30m) that only fires when burn is elevated on both the
  long and short window, so blips never page anyone. The `burn` CLI accepts
  custom rules in its JSON spec when the defaults do not fit a service, and
  emits the firing rules as JSON (`--json`) for paging pipelines.
  `burn --suggest --slo 0.999 --window-days 30` emits a ready-to-edit policy
  template: the standard three-tier table (page at 2% of budget in 1h, fast
  ticket at 5% in 6h, slow ticket at 10% in 3d) with burn thresholds scaled
  to the window, ready to drop into a burn spec's `rules`.
  `burn spec.json --replay` replays a time series of timestamped
  total/bad buckets through the rules: at every bucket tick each rule's
  long and short trailing windows are re-evaluated, and the report lists
  every firing interval per rule (start, end, tick count) - the "would
  this policy have paged us, and for how long" answer when tuning
  thresholds against a past incident. Exits 1 when any critical rule
  fired during the replay, and emits the intervals under `--json`.
- **Status reports** - render a Markdown SLO status report (table plus
  plain-language status lines) from a JSON list of SLO window snapshots;
  snapshots carrying their `window_days` also get an exhaustion projection
  ("budget exhausts in ~3.0 days at current burn"). Exits 1 when any budget
  is exhausted, so it can gate a cron job or CI pipeline, `--json`
  emits the same per-SLO detail for dashboards and tooling, and
  `--worst-first` sorts by budget consumed so long fleet reviews surface
  the SLOs that need action first.
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
python -m sre_toolkit triage examples/alerts.json --top-talkers   # noisiest deduped alerts first
python -m sre_toolkit triage examples/alerts.json --by-severity   # active alerts per severity
python -m sre_toolkit triage examples/alerts.json --silences examples/silences.json
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

242 tests cover the budget math (including boundary and validation cases),
severity classification, dedupe, ordering, grouping, severity and noise
roll-ups, silence validation, matching and expiry, burn-rate rules, policy suggestion and
time-series replay,
postmortem rendering, report rendering with fleet summaries, SLO document
rendering (Markdown and JSON), metrics aggregation (per severity, per
service, per week), action-item follow-through, and the CLI commands.

## Layout

```
sre_toolkit/
  error_budget.py   # SLO budget, burn rate, downtime, exhaustion projection
  alert_triage.py   # severity rules, dedupe, severity ordering, grouping
  silences.py       # bounded alert silences with matchers, reasons, expiry
  postmortem.py     # structured incident -> Markdown postmortem
  burn_alerts.py    # multi-window burn-rate alerting rules
  report.py         # Markdown SLO status report from window snapshots
  slo_doc.py        # SLO definition documents (Markdown + JSON payload)
  __main__.py       # CLI: budget / downtime / triage / report / burn / postmortem / slo-doc
tests/              # unittest suite, no external dependencies
examples/           # sample alert input for the CLI
```
