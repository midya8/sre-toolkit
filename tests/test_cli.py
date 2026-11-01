import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sre_toolkit.__main__ import main


def _run_args(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    return code, buf.getvalue()


def _run(argv, payload=None):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "input.json"
        path.write_text(json.dumps(payload))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv + [str(path)])
        return code, buf.getvalue()


class TestBudgetCLI(unittest.TestCase):
    def test_bad_event_counts_in_text(self):
        code, out = _run_args(["budget", "--slo", "0.999", "--total", "10000", "--bad", "5"])
        self.assertEqual(code, 0)
        self.assertIn("Bad events:        5 of 10 allowed (5 left)", out)

    def test_bad_event_counts_in_json(self):
        code, out = _run_args(["budget", "--slo", "0.999", "--total", "10000", "--bad", "5", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["allowed_bad_events"], 10)
        self.assertEqual(data["remaining_bad_events"], 5)

    def test_exhaustion_projection(self):
        code, out = _run_args(
            ["budget", "--slo", "0.999", "--total", "10000", "--bad", "5",
             "--window-days", "30"])
        self.assertEqual(code, 0)
        self.assertIn("Exhaustion:        ~15.0 days at current burn", out)

    def test_no_projection_without_window(self):
        _, out = _run_args(["budget", "--slo", "0.999", "--total", "10000", "--bad", "5"])
        self.assertNotIn("Exhaustion", out)

    def test_zero_burn_not_projected(self):
        _, out = _run_args(
            ["budget", "--slo", "0.999", "--total", "10000", "--bad", "0",
             "--window-days", "30"])
        self.assertIn("not projected (zero burn)", out)

    def test_json_output(self):
        code, out = _run_args(
            ["budget", "--slo", "0.999", "--total", "10000", "--bad", "5",
             "--window-days", "30", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total_events"], 10000)
        self.assertEqual(data["bad_events"], 5)
        self.assertFalse(data["budget_exhausted"])
        self.assertAlmostEqual(data["burn_rate"], 0.5, places=6)
        self.assertAlmostEqual(data["exhaustion_days"], 15.0, places=6)

    def test_json_zero_burn_projects_null(self):
        code, out = _run_args(
            ["budget", "--slo", "0.999", "--total", "10000", "--bad", "0",
             "--window-days", "30", "--json"])
        self.assertEqual(code, 0)
        self.assertIsNone(json.loads(out)["exhaustion_days"])

    def test_json_exhausted_still_exits_1(self):
        code, out = _run_args(
            ["budget", "--slo", "0.999", "--total", "1000", "--bad", "10", "--json"])
        self.assertEqual(code, 1)
        self.assertTrue(json.loads(out)["budget_exhausted"])

    def test_exhausted_budget_exits_1(self):
        code, out = _run_args(
            ["budget", "--slo", "0.999", "--total", "1000", "--bad", "10",
             "--window-days", "30"])
        self.assertEqual(code, 1)
        self.assertIn("budget already exhausted", out)


class TestDowntimeCLI(unittest.TestCase):
    def test_table_without_days(self):
        code, out = _run_args(["downtime", "--slo", "0.999"])
        self.assertEqual(code, 0)
        self.assertIn("30 days:     43.2 minutes", out)
        self.assertIn(" 1 days:", out.replace("   1 days:", " 1 days:"))

    def test_single_window_unchanged(self):
        code, out = _run_args(["downtime", "--slo", "0.999", "--days", "30"])
        self.assertEqual(code, 0)
        self.assertIn("Allowed downtime: 43.2 minutes over 30 days", out)

    def test_json_table(self):
        code, out = _run_args(["downtime", "--slo", "0.999", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertAlmostEqual(data["allowed_downtime_minutes"]["30"], 43.2, places=6)
        self.assertEqual(set(data["allowed_downtime_minutes"]), {"1", "7", "30", "90"})

    def test_json_single_window(self):
        code, out = _run_args(["downtime", "--slo", "0.999", "--days", "30", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["window_days"], 30.0)
        self.assertAlmostEqual(data["allowed_downtime_minutes"], 43.2, places=6)


class TestBurnCLI(unittest.TestCase):
    def test_firing_critical_returns_1(self):
        code, out = _run(["burn"], {
            "slo": 0.999,
            "samples": [
                {"window_hours": 1, "total": 360000, "bad": 5200},
                {"window_hours": 0.0833, "total": 30000, "bad": 440},
            ],
        })
        self.assertEqual(code, 1)
        self.assertIn("[critical] page", out)

    def test_quiet_windows_return_0(self):
        code, out = _run(["burn"], {
            "slo": 0.999,
            "samples": [
                {"window_hours": 1, "total": 360000, "bad": 100},
                {"window_hours": 0.0833, "total": 30000, "bad": 8},
            ],
        })
        self.assertEqual(code, 0)
        self.assertIn("No burn-rate rules firing.", out)

    def test_missing_window_samples_skips_rule(self):
        code, out = _run(["burn"], {
            "slo": 0.999,
            "samples": [{"window_hours": 24, "total": 1000, "bad": 500}],
        })
        self.assertEqual(code, 0)
        self.assertIn("No burn-rate rules firing.", out)


class TestTriageCLI(unittest.TestCase):
    ALERTS = [
        {"alert_id": "a1", "service": "web", "summary": "Weekly report ready"},
        {"alert_id": "a2", "service": "api", "summary": "Service down"},
        {"alert_id": "a3", "service": "api", "summary": "Error rate elevated"},
    ]

    def test_by_service_groups_and_worst(self):
        code, out = _run(["triage", "--by-service"], self.ALERTS)
        self.assertEqual(code, 0)
        self.assertIn("api (2 alerts, worst: critical)", out)
        self.assertIn("web (1 alert, worst: low)", out)
        self.assertLess(out.index("api"), out.index("web"))

    def test_json_output(self):
        code, out = _run(["triage", "--json"], self.ALERTS)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]["severity"], "critical")
        self.assertEqual(data[0]["service"], "api")

    def test_default_output_unchanged(self):
        code, out = _run(["triage"], self.ALERTS)
        self.assertEqual(code, 0)
        self.assertIn("[critical] api", out)

    def test_repeat_count_shown_for_duplicates(self):
        alerts = self.ALERTS + [{"alert_id": "a4", "service": "api", "summary": "service   DOWN"}]
        code, out = _run(["triage"], alerts)
        self.assertEqual(code, 0)
        self.assertIn("Service down (x2)", out)
        self.assertNotIn("(x1)", out)

    def test_repeat_count_in_json(self):
        alerts = self.ALERTS + [{"alert_id": "a4", "service": "api", "summary": "service   DOWN"}]
        code, out = _run(["triage", "--json"], alerts)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 3)  # duplicate collapsed
        self.assertEqual(data[0]["occurrences"], 2)
        self.assertEqual(data[1]["occurrences"], 1)

    def test_inhibit_flag_suppresses_symptoms(self):
        # api has a critical, so its high-severity alerts are inhibited;
        # web's low alert stays (no critical on web)
        code, out = _run(["triage", "--inhibit"], self.ALERTS)
        self.assertEqual(code, 0)
        kept = out.split("(1 alert inhibited")[0]
        self.assertIn("[critical] api", kept)
        self.assertIn("[low     ] web", kept)
        self.assertNotIn("Error rate elevated", kept)
        self.assertIn("(1 alert inhibited: symptoms of a critical on the same service)", out)
        self.assertIn("Error rate elevated", out)

    def test_inhibit_json_separates_inhibited(self):
        code, out = _run(["triage", "--inhibit", "--json"], self.ALERTS)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data["alerts"]), 2)
        self.assertEqual(len(data["inhibited"]), 1)
        self.assertEqual(data["inhibited"][0]["alert_id"], "a3")

    def test_json_without_inhibit_stays_a_list(self):
        code, out = _run(["triage", "--json"], self.ALERTS)
        self.assertEqual(code, 0)
        self.assertIsInstance(json.loads(out), list)

    def test_repeat_count_in_by_service(self):
        alerts = self.ALERTS + [{"alert_id": "a4", "service": "api", "summary": "service   DOWN"}]
        code, out = _run(["triage", "--by-service"], alerts)
        self.assertEqual(code, 0)
        self.assertIn("api (2 alerts, worst: critical)", out)
        self.assertIn("Service down (x2)", out)


class TestTriageCustomRules(unittest.TestCase):
    ALERTS = [
        {"alert_id": "a1", "service": "api", "summary": "SEV1 customer impact"},
        {"alert_id": "a2", "service": "api", "summary": "flaky CI"},
    ]

    def _run_with_rules(self, rules):
        with tempfile.TemporaryDirectory() as tmp:
            alerts = Path(tmp) / "alerts.json"
            alerts.write_text(json.dumps(self.ALERTS))
            spec = Path(tmp) / "rules.json"
            spec.write_text(json.dumps(rules))
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["triage", str(alerts), "--rules", str(spec)])
            return code, buf.getvalue()

    def test_custom_rules_applied(self):
        code, out = self._run_with_rules({"critical": ["sev1"], "medium": ["flaky"]})
        self.assertEqual(code, 0)
        self.assertIn("[critical] api", out)
        self.assertIn("[medium  ] api", out)

    def test_bad_rules_exit_2(self):
        code, out = self._run_with_rules({"urgent": ["now"]})
        self.assertEqual(code, 2)


class TestBurnCustomRules(unittest.TestCase):
    SPEC = {
        "slo": 0.99,
        "samples": [
            {"window_hours": 2, "total": 100000, "bad": 3000},
            {"window_hours": 0.25, "total": 12500, "bad": 400},
        ],
    }

    def test_custom_rule_fires(self):
        payload = dict(self.SPEC, rules=[
            {"name": "fast-page", "severity": "critical", "burn_threshold": 2.5,
             "long_window_hours": 2, "short_window_hours": 0.25},
        ])
        code, out = _run(["burn"], payload)
        self.assertEqual(code, 1)
        self.assertIn("[critical] fast-page", out)

    def test_custom_rule_above_burn_does_not_fire(self):
        payload = dict(self.SPEC, rules=[
            {"name": "extreme", "severity": "critical", "burn_threshold": 50,
             "long_window_hours": 2, "short_window_hours": 0.25},
        ])
        code, out = _run(["burn"], payload)
        self.assertEqual(code, 0)
        self.assertIn("No burn-rate rules firing.", out)

    def test_custom_rules_replace_defaults(self):
        # With the default 14.4x page rule this 3x-burn spec stays quiet.
        code, out = _run(["burn"], self.SPEC)
        self.assertEqual(code, 0)
        self.assertIn("No burn-rate rules firing.", out)

    def test_json_output_with_firing(self):
        payload = dict(self.SPEC, rules=[
            {"name": "fast-page", "severity": "critical", "burn_threshold": 2.5,
             "long_window_hours": 2, "short_window_hours": 0.25},
        ])
        code, out = _run(["burn", "--json"], payload)
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(data["slo"], 0.99)
        self.assertEqual(data["firing"][0]["name"], "fast-page")

    def test_json_output_quiet(self):
        code, out = _run(["burn", "--json"], self.SPEC)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["firing"], [])

    def test_invalid_rule_returns_2(self):
        payload = dict(self.SPEC, rules=[{"name": "broken"}])
        code, _ = _run(["burn"], payload)
        self.assertEqual(code, 2)


class TestPostmortemCLI(unittest.TestCase):
    PAYLOAD = {
        "title": "Outage",
        "severity": "SEV1",
        "started": "2026-10-28 14:05 UTC",
        "detected": "2026-10-28 14:12 UTC",
        "resolved": "2026-10-28 14:47 UTC",
        "services": ["api"],
        "summary": "s",
        "impact": "i",
        "root_cause": "r",
        "timeline": [["14:05", "start"]],
        "action_items": ["fix it"],
    }

    def test_renders_postmortem(self):
        code, out = _run(["postmortem"], self.PAYLOAD)
        self.assertEqual(code, 0)
        self.assertIn("# Postmortem: Outage", out)
        self.assertIn("SEV1", out)

    def test_json_metrics(self):
        code, out = _run(["postmortem", "--json"], self.PAYLOAD)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["title"], "Outage")
        self.assertEqual(data["time_to_detect_minutes"], 7.0)
        self.assertEqual(data["time_to_resolve_minutes"], 35.0)
        self.assertEqual(data["total_duration_minutes"], 42.0)

    def test_json_nulls_when_uncomputable(self):
        payload = dict(self.PAYLOAD, started="unknown", detected="unknown",
                       resolved="unknown")
        code, out = _run(["postmortem", "--json"], payload)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIsNone(data["time_to_detect_minutes"])
        self.assertIsNone(data["total_duration_minutes"])

    def test_optional_fields_default(self):
        payload = {k: v for k, v in self.PAYLOAD.items()
                   if k not in ("services", "timeline", "action_items")}
        code, out = _run(["postmortem"], payload)
        self.assertEqual(code, 0)
        self.assertIn("# Postmortem: Outage", out)


class TestSloDocCLI(unittest.TestCase):
    def test_renders_doc(self):
        code, out = _run(["slo-doc"], {
            "name": "Checkout availability",
            "service": "checkout-api",
            "target": 0.999,
            "window_days": 30,
            "sli": "Share of requests without a 5xx.",
        })
        self.assertEqual(code, 0)
        self.assertIn("# SLO: Checkout availability", out)
        self.assertIn("_No alert thresholds defined._", out)

    def test_json_output(self):
        code, out = _run(["slo-doc", "--json"], {
            "name": "Checkout availability",
            "service": "checkout-api",
            "target": 0.999,
            "window_days": 30,
            "sli": "Share of requests without a 5xx.",
            "alert_thresholds": ["page at 14.4x burn over 1h + 5m"],
        })
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["name"], "Checkout availability")
        self.assertEqual(payload["service"], "checkout-api")
        self.assertEqual(payload["alert_thresholds"], ["page at 14.4x burn over 1h + 5m"])
        self.assertAlmostEqual(payload["error_budget"]["budget_fraction"], 0.001)
        self.assertAlmostEqual(payload["error_budget"]["allowed_downtime_minutes"], 43.2)
        self.assertNotIn("# SLO:", out)


class TestMetricsCLI(unittest.TestCase):
    INCIDENTS = [
        {"title": "a", "severity": "high", "started": "2026-10-30 14:05 UTC",
         "detected": "2026-10-30 14:12 UTC", "resolved": "2026-10-30 15:40 UTC",
         "summary": "s", "impact": "i", "root_cause": "r"},
        {"title": "b", "severity": "low", "started": "unknown", "detected": "unknown",
         "resolved": "unknown", "summary": "s", "impact": "i", "root_cause": "r"},
    ]

    def test_aggregates_with_skip_note(self):
        code, out = _run(["metrics"], self.INCIDENTS)
        self.assertEqual(code, 0)
        self.assertIn("Incidents analyzed: 1 (1 skipped, timestamps unparseable)", out)
        self.assertIn("Time to detect:  mean 7 minutes, median 7 minutes, p90 7 minutes", out)
        self.assertIn("Time to resolve: mean 1 hour 28 minutes, median 1 hour 28 minutes, "
                      "p90 1 hour 28 minutes", out)

    def test_by_week_text(self):
        code, out = _run(["metrics", "--by-week"], self.INCIDENTS)
        self.assertEqual(code, 0)
        self.assertIn("By week:", out)
        self.assertIn("2026-W44: n=1, mean TTD 7 minutes, mean TTR 1 hour 28 minutes", out)

    def test_by_week_not_printed_without_flag(self):
        code, out = _run(["metrics"], self.INCIDENTS)
        self.assertEqual(code, 0)
        self.assertNotIn("By week:", out)

    def test_by_week_json(self):
        code, out = _run(["metrics", "--json", "--by-week"], self.INCIDENTS)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["by_week"], [{
            "week": "2026-W44", "incidents": 1,
            "mean_time_to_detect_minutes": 7.0,
            "mean_time_to_resolve_minutes": 88.0,
        }])

    def test_json_output(self):
        code, out = _run(["metrics", "--json"], self.INCIDENTS)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["incidents"], 1)
        self.assertEqual(data["skipped"], 1)
        self.assertEqual(data["time_to_detect_minutes"],
                         {"mean": 7.0, "median": 7.0, "p90": 7.0})
        self.assertEqual(data["time_to_resolve_minutes"],
                         {"mean": 88.0, "median": 88.0, "p90": 88.0})

    def test_json_by_severity(self):
        incidents = [
            {"title": "a", "severity": "high", "started": "2026-10-30 14:05 UTC",
             "detected": "2026-10-30 14:12 UTC", "resolved": "2026-10-30 15:40 UTC",
             "summary": "s", "impact": "i", "root_cause": "r"},
            {"title": "b", "severity": "low", "started": "2026-10-28 09:00 UTC",
             "detected": "2026-10-28 09:30 UTC", "resolved": "2026-10-28 10:00 UTC",
             "summary": "s", "impact": "i", "root_cause": "r"},
        ]
        code, out = _run(["metrics", "--json"], incidents)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["by_severity"]["high"],
                         {"incidents": 1, "mean_time_to_detect_minutes": 7.0,
                          "mean_time_to_resolve_minutes": 88.0})
        self.assertEqual(data["by_severity"]["low"]["incidents"], 1)

    def test_text_by_severity_only_when_multiple(self):
        incidents = [
            {"title": "a", "severity": "high", "started": "2026-10-30 14:05 UTC",
             "detected": "2026-10-30 14:12 UTC", "resolved": "2026-10-30 15:40 UTC",
             "summary": "s", "impact": "i", "root_cause": "r"},
            {"title": "b", "severity": "low", "started": "2026-10-28 09:00 UTC",
             "detected": "2026-10-28 09:30 UTC", "resolved": "2026-10-28 10:00 UTC",
             "summary": "s", "impact": "i", "root_cause": "r"},
        ]
        code, out = _run(["metrics"], incidents)
        self.assertEqual(code, 0)
        self.assertIn("By severity:", out)
        self.assertIn("high: n=1, mean TTD 7 minutes", out)
        # single-severity input stays quiet
        code, out = _run(["metrics"], [self.INCIDENTS[0]])
        self.assertNotIn("By severity:", out)

    def test_json_exit_2_when_nothing_computable(self):
        code, out = _run(["metrics", "--json"], [self.INCIDENTS[1]])
        self.assertEqual(code, 2)

    def test_exit_2_when_nothing_computable(self):
        code, out = _run(["metrics"], [self.INCIDENTS[1]])
        self.assertEqual(code, 2)


class TestReportCLI(unittest.TestCase):
    def test_renders_report(self):
        code, out = _run(["report"], [
            {"name": "api", "slo": 0.999, "total": 10000, "bad": 5},
        ])
        self.assertEqual(code, 0)
        self.assertIn("# SLO status report", out)
        self.assertIn("| api |", out)

    def test_worst_first_sorts_rows(self):
        code, out = _run(["report", "--worst-first"], [
            {"name": "api", "slo": 0.999, "total": 10000, "bad": 5},
            {"name": "worker", "slo": 0.99, "total": 1000, "bad": 8},
        ])
        self.assertEqual(code, 0)
        self.assertLess(out.index("| worker |"), out.index("| api |"))

    def test_worst_first_json_sorted(self):
        code, out = _run(["report", "--json", "--worst-first"], [
            {"name": "api", "slo": 0.999, "total": 10000, "bad": 5},
            {"name": "worker", "slo": 0.99, "total": 1000, "bad": 8},
        ])
        self.assertEqual(code, 0)
        self.assertLess(out.index('"worker"'), out.index('"api"'))

    def test_exit_1_when_any_budget_exhausted(self):
        code, _ = _run(["report"], [
            {"name": "api", "slo": 0.999, "total": 1000, "bad": 10},
            {"name": "worker", "slo": 0.99, "total": 1000, "bad": 0},
        ])
        self.assertEqual(code, 1)

    def test_json_output_shape(self):
        code, out = _run(["report", "--json"], [
            {"name": "api", "slo": 0.999, "total": 250000, "bad": 120, "window_days": 30},
            {"name": "idle", "slo": 0.99, "total": 0, "bad": 0},
        ])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertFalse(data["exhausted"])
        self.assertEqual(len(data["slos"]), 2)
        api, idle = data["slos"]
        self.assertEqual(api["status"], "healthy")
        self.assertAlmostEqual(api["burn_rate"], 0.48)
        self.assertAlmostEqual(api["exhaustion_days"], 15.6)
        self.assertEqual(idle["status"], "no_events")
        self.assertIsNone(idle["error_rate"])

    def test_json_keeps_exit_1_when_exhausted(self):
        code, out = _run(["report", "--json"], [
            {"name": "api", "slo": 0.999, "total": 1000, "bad": 10},
        ])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertTrue(data["exhausted"])
        self.assertEqual(data["slos"][0]["status"], "exhausted")

    def test_window_days_adds_projection(self):
        code, out = _run(["report"], [
            {"name": "api", "slo": 0.999, "total": 250000, "bad": 120, "window_days": 30},
        ])
        self.assertEqual(code, 0)
        self.assertIn("At current burn the budget exhausts in ~15.6 days.", out)

    def test_no_window_days_keeps_plain_line(self):
        code, out = _run(["report"], [
            {"name": "api", "slo": 0.999, "total": 250000, "bad": 120},
        ])
        self.assertEqual(code, 0)
        self.assertNotIn("At current burn", out)

    def test_exit_0_when_all_healthy(self):
        code, _ = _run(["report"], [
            {"name": "api", "slo": 0.999, "total": 1000, "bad": 0},
            {"name": "idle", "slo": 0.99, "total": 0, "bad": 0},
        ])
        self.assertEqual(code, 0)


class TestTopTalkersCLI(unittest.TestCase):
    STREAM = [
        {"alert_id": f"n{i}", "service": "db", "summary": "Weekly report ready"}
        for i in range(5)
    ] + [
        {"alert_id": "c1", "service": "web", "summary": "Service down"},
    ]

    def test_text_output(self):
        code, out = _run(["triage", "--top-talkers"], self.STREAM)
        self.assertEqual(code, 0)
        self.assertIn("Top talkers (deduped, by occurrences):", out)
        self.assertIn("   5x [low     ] db: Weekly report ready", out)
        self.assertLess(out.index("5x"), out.index("1x"))

    def test_json_output(self):
        code, out = _run(["triage", "--json", "--top-talkers"], self.STREAM)
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["top_talkers"][0]["occurrences"], 5)
        self.assertEqual(payload["top_talkers"][0]["service"], "db")

    def test_absent_without_flag(self):
        code, out = _run(["triage"], self.STREAM)
        self.assertEqual(code, 0)
        self.assertNotIn("Top talkers", out)


class TestReportSummaryCLI(unittest.TestCase):
    SNAPS = [
        {"name": "healthy-api", "slo": 0.999, "total": 10000, "bad": 1},
        {"name": "down-api", "slo": 0.999, "total": 10000, "bad": 20},
    ]

    def test_summary_text(self):
        code, out = _run(["report", "--summary"], self.SNAPS)
        self.assertEqual(code, 1)  # down-api is exhausted: report still gates
        self.assertIn("## Fleet summary", out)
        self.assertIn("- Worst: down-api", out)

    def test_summary_json(self):
        code, out = _run(["report", "--json", "--summary"], self.SNAPS)
        self.assertEqual(code, 1)
        summary = json.loads(out)["fleet_summary"]
        self.assertEqual(summary["exhausted"], 1)
        self.assertEqual(summary["worst_slo"], "down-api")

    def test_summary_absent_without_flag(self):
        code, out = _run(["report", "--json"], self.SNAPS)
        self.assertNotIn("fleet_summary", json.loads(out))


class TestTriageBySeverityCLI(unittest.TestCase):
    ALERTS = [
        {"alert_id": "a", "service": "web", "summary": "Service down"},
        {"alert_id": "b", "service": "db", "summary": "Error rate elevated"},
        {"alert_id": "c", "service": "db", "summary": "Weekly report ready"},
    ]

    def test_text_output(self):
        code, out = _run(["triage", "--by-severity"], self.ALERTS)
        self.assertEqual(code, 0)
        self.assertIn("Severity counts: critical 1, high 1, low 1", out)

    def test_json_output(self):
        code, out = _run(["triage", "--json", "--by-severity"], self.ALERTS)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["by_severity"],
                         {"critical": 1, "high": 1, "low": 1})


class TestMetricsByServiceCLI(unittest.TestCase):
    INCIDENTS = [
        {"title": "a", "severity": "high", "started": "2026-10-30 14:05 UTC",
         "detected": "2026-10-30 14:12 UTC", "resolved": "2026-10-30 15:40 UTC",
         "services": ["checkout", "payments"], "summary": "s", "impact": "i",
         "root_cause": "r"},
        {"title": "b", "severity": "low", "started": "2026-10-29 09:00 UTC",
         "detected": "2026-10-29 09:10 UTC", "resolved": "2026-10-29 10:00 UTC",
         "services": ["checkout"], "summary": "s", "impact": "i",
         "root_cause": "r"},
    ]

    def test_text_output(self):
        code, out = _run(["metrics", "--by-service"], self.INCIDENTS)
        self.assertEqual(code, 0)
        self.assertIn("By service:", out)
        self.assertIn("checkout: n=2", out)
        self.assertIn("payments: n=1", out)

    def test_json_output(self):
        code, out = _run(["metrics", "--json", "--by-service"], self.INCIDENTS)
        self.assertEqual(code, 0)
        by_service = json.loads(out)["by_service"]
        self.assertEqual(by_service["checkout"]["incidents"], 2)
        self.assertEqual(by_service["payments"]["incidents"], 1)

    def test_absent_without_flag(self):
        code, out = _run(["metrics"], self.INCIDENTS)
        self.assertEqual(code, 0)
        self.assertNotIn("By service:", out)


if __name__ == "__main__":
    unittest.main()


class TestTriageSilences(unittest.TestCase):
    SILENCED = [
        {"alert_id": "a1", "service": "web", "summary": "Weekly report ready"},
        {"alert_id": "a2", "service": "api", "summary": "Service down"},
    ]

    def _silences_file(self, tmp):
        import json as _json
        from pathlib import Path as _Path
        path = _Path(tmp) / "silences.json"
        path.write_text(_json.dumps([
            {"severity": "low", "reason": "known noise", "until": "2999-01-01T00:00:00Z"}]))
        return str(path)

    def test_silenced_alerts_move_to_their_own_section(self):
        import json as _json, subprocess, sys
        from pathlib import Path as _Path
        from tempfile import TemporaryDirectory as _TD
        with _TD() as tmp:
            alerts_path = _Path(tmp) / "alerts.json"
            alerts_path.write_text(_json.dumps(self.SILENCED))
            out = subprocess.run(
                [sys.executable, "-m", "sre_toolkit", "triage", str(alerts_path),
                 "--silences", self._silences_file(tmp)],
                capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertIn("1 alert silenced", out.stdout)
        self.assertIn("known noise", out.stdout)
        # the silenced low alert no longer appears in the main list
        main_list = out.stdout.split("(1 alert silenced)")[0]
        self.assertNotIn("Weekly report", main_list)
        self.assertIn("Service down", main_list)

    def test_silenced_in_json_payload(self):
        import json as _json, subprocess, sys
        from pathlib import Path as _Path
        from tempfile import TemporaryDirectory as _TD
        with _TD() as tmp:
            alerts_path = _Path(tmp) / "alerts.json"
            alerts_path.write_text(_json.dumps(self.SILENCED))
            out = subprocess.run(
                [sys.executable, "-m", "sre_toolkit", "triage", str(alerts_path),
                 "--silences", self._silences_file(tmp), "--json"],
                capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        payload = _json.loads(out.stdout)
        self.assertEqual(len(payload["alerts"]), 1)
        self.assertEqual(payload["silenced"][0]["silenced_reason"], "known noise")

    def test_bad_silences_file_exit_2(self):
        import json as _json, subprocess, sys
        from pathlib import Path as _Path
        from tempfile import TemporaryDirectory as _TD
        with _TD() as tmp:
            alerts_path = _Path(tmp) / "alerts.json"
            alerts_path.write_text(_json.dumps(self.SILENCED))
            bad = _Path(tmp) / "bad.json"
            bad.write_text(_json.dumps([{"reason": "r"}]))  # no 'until'
            out = subprocess.run(
                [sys.executable, "-m", "sre_toolkit", "triage", str(alerts_path),
                 "--silences", str(bad)],
                capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)
        self.assertIn("bad silences file", out.stderr)


class TestBurnSuggest(unittest.TestCase):
    def _run(self, *argv):
        import subprocess, sys
        return subprocess.run([sys.executable, "-m", "sre_toolkit", "burn", *argv],
                              capture_output=True, text=True)

    def test_suggest_emits_a_usable_policy_template(self):
        import json as _json
        out = self._run("--suggest", "--slo", "0.999")
        self.assertEqual(out.returncode, 0)
        payload = _json.loads(out.stdout)
        self.assertEqual(payload["slo"], 0.999)
        self.assertEqual(payload["samples"], [])
        self.assertAlmostEqual(payload["rules"][0]["burn_threshold"], 14.4, places=3)

    def test_suggest_validates_inputs(self):
        self.assertEqual(self._run("--suggest", "--slo", "1.5").returncode, 2)
        self.assertEqual(self._run("--suggest", "--window-days", "2").returncode, 2)

    def test_burn_without_file_or_suggest_exit_2(self):
        out = self._run()
        self.assertEqual(out.returncode, 2)
        self.assertIn("--suggest", out.stderr)


class TestMetricsActionItems(unittest.TestCase):
    INCIDENTS = [
        {"title": "old outage", "severity": "high",
         "started": "2026-10-01 10:00 UTC", "detected": "2026-10-01 10:05 UTC",
         "resolved": "2026-10-01 11:00 UTC", "summary": "s", "impact": "i",
         "root_cause": "r",
         "action_items": ["add alerting", {"item": "file postmortem", "done": True}]},
        {"title": "recent blip", "severity": "low",
         "started": "unknown", "detected": "unknown", "resolved": "unknown",
         "summary": "s", "impact": "i", "root_cause": "r",
         "action_items": ["tweak dashboard"]},
    ]

    def test_text_lists_open_items_per_incident(self):
        code, out = _run(["metrics", "--action-items"], self.INCIDENTS)
        self.assertIn("Action items: 2 open across 2 incidents", out)
        self.assertIn("old outage", out)
        self.assertIn("- [ ] add alerting", out)
        self.assertIn("- [ ] tweak dashboard", out)

    def test_exit_1_when_open_items_stale(self):
        code, out = _run(["metrics", "--action-items"], self.INCIDENTS)
        self.assertEqual(code, 1)
        self.assertIn("STALE", out)

    def test_stale_days_override_changes_exit(self):
        code, out = _run(["metrics", "--action-items", "--stale-days", "400"],
                         self.INCIDENTS)
        self.assertEqual(code, 0)
        self.assertNotIn("STALE", out)

    def test_json_block_and_stale_exit(self):
        code, out = _run(["metrics", "--action-items", "--json"], self.INCIDENTS)
        self.assertEqual(code, 1)
        data = json.loads(out)
        followup = data["action_items"]
        self.assertEqual(followup["open_items_total"], 2)
        self.assertEqual(followup["stale_incidents"], 1)
        self.assertEqual(followup["incidents"][0]["title"], "old outage")

    def test_bad_action_item_exits_2(self):
        incidents = [dict(self.INCIDENTS[0], action_items=[{"done": True}])]
        code, out = _run(["metrics", "--action-items"], incidents)
        self.assertEqual(code, 2)

    def test_no_flag_means_no_followup(self):
        code, out = _run(["metrics"], self.INCIDENTS)
        self.assertEqual(code, 0)
        self.assertNotIn("Action items:", out)


class TestMetricsActionItemsOnly(unittest.TestCase):
    def test_all_timestamps_unparseable_still_reports_followup(self):
        incidents = [
            {"title": "mystery", "severity": "low", "started": "?", "detected": "?",
             "resolved": "long ago", "summary": "s", "impact": "i", "root_cause": "r",
             "action_items": ["follow up"]},
        ]
        code, out = _run(["metrics", "--action-items"], incidents)
        self.assertEqual(code, 0)
        self.assertIn("No incidents with parseable timestamps.", out)
        self.assertIn("Action items: 1 open across 1 incidents", out)


class TestBurnReplayCLI(unittest.TestCase):
    QUIET = {"slo": 0.999, "buckets": [
        {"timestamp": f"2026-10-31T20:{m:02d}:00Z", "total": 30000, "bad": 20}
        for m in range(0, 60, 5)]}
    HOT = {"slo": 0.999, "buckets": [
        {"timestamp": f"2026-10-31T20:{m:02d}:00Z", "total": 30000,
         "bad": 3000 if 30 <= m < 45 else 20}
        for m in range(0, 60, 5)]}

    def test_text_quiet_never_fired(self):
        code, out = _run(["burn", "--replay"], self.QUIET)
        self.assertEqual(code, 0)
        self.assertIn("Replay over 12 buckets:", out)
        self.assertIn("page: never fired", out)
        self.assertIn("ticket: never fired", out)

    def test_text_hot_lists_interval_and_exits_1(self):
        code, out = _run(["burn", "--replay"], self.HOT)
        self.assertEqual(code, 1)
        self.assertIn("page: fired 2026-10-31T20:30:00+00:00 -> "
                      "2026-10-31T20:40:00+00:00 (3 ticks)", out)

    def test_json_report(self):
        code, out = _run(["burn", "--replay", "--json"], self.HOT)
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(data["buckets"], 12)
        page = next(r for r in data["rules"] if r["name"] == "page")
        self.assertEqual(page["firing_ticks"], 3)
        self.assertEqual(page["intervals"][0]["start"],
                         "2026-10-31T20:30:00+00:00")
        ticket = next(r for r in data["rules"] if r["name"] == "ticket")
        self.assertGreater(ticket["firing_ticks"], 0)

    def test_custom_rules_in_replay_file(self):
        spec = dict(self.HOT, rules=[{
            "name": "any-error", "severity": "medium", "burn_threshold": 0.5,
            "long_window_hours": 1, "short_window_hours": 5 / 60}])
        code, out = _run(["burn", "--replay"], spec)
        self.assertEqual(code, 0)  # no critical rule -> exit 0
        self.assertIn("any-error", out)
        self.assertNotIn("page:", out)

    def test_bad_replay_file_exits_2(self):
        code, out = _run(["burn", "--replay"], {"slo": 0.999, "buckets": []})
        self.assertEqual(code, 2)
