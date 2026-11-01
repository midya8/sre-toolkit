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


class TestReportCLI(unittest.TestCase):
    def test_renders_report(self):
        code, out = _run(["report"], [
            {"name": "api", "slo": 0.999, "total": 10000, "bad": 5},
        ])
        self.assertEqual(code, 0)
        self.assertIn("# SLO status report", out)
        self.assertIn("| api |", out)


if __name__ == "__main__":
    unittest.main()
