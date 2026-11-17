# sre-toolkit

Python helpers for the SRE chores I kept redoing by hand: error budget and burn rate math, sorting a noisy alert list, and writing up postmortems. Standard library only, Python 3.10+.

```bash
python -m sre_toolkit budget --slo 0.999 --total 10000 --bad 5 --window-days 30
python -m sre_toolkit downtime --slo 0.999
python -m sre_toolkit triage examples/alerts.json --silences examples/silences.json
python -m sre_toolkit burn examples/burn-samples.json
python -m sre_toolkit postmortem examples/incident.json
python -m sre_toolkit metrics examples/incidents.json --by-service
```

Other subcommands: `report` (SLO snapshot summary), `slo-doc` (writes an SLO definition doc), and `burn --suggest` / `burn --replay` for picking burn-rate thresholds and replaying a time series.

It also works as a library:

```python
from sre_toolkit.error_budget import compute_error_budget, allowed_downtime_minutes

b = compute_error_budget(slo=0.999, total_events=10_000, bad_events=5)
print(b.consumed_fraction, b.burn_rate)
print(allowed_downtime_minutes(0.999, 30))   # about 43.2 minutes
```

A few notes on behaviour:

- Triage is keyword based by default. Pass `--rules` to use your own words, `--routes` to assign owners. Silenced alerts get moved to their own section rather than dropped.
- The default burn rules page at 14.4x (1h and 5m windows) and ticket at 6x (6h and 30m). Both windows have to cross before anything fires.
- The exhaustion estimate in `report` is a straight line from the current burn rate, so treat it as a rough guess.
- `budget`, `report`, `burn` and `metrics --action-items` exit 1 when something needs attention, so they can sit in a cron job or CI step.

Tests: `python -m unittest discover -s tests` (254 of them).
