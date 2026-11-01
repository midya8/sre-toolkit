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


if __name__ == "__main__":
    unittest.main()
