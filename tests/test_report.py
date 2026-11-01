import unittest

from sre_toolkit.report import SLOSnapshot, render_report, snapshot_summary


class TestRenderReport(unittest.TestCase):
    def test_empty_report(self):
        out = render_report([])
        self.assertIn("# SLO status report", out)
        self.assertIn("_no SLOs_", out)

    def test_table_row_values(self):
        out = render_report([SLOSnapshot("API", 0.999, 10_000, 5)])
        self.assertIn("| API | 99.90% | 0.0500% | 50.0% | 0.50x |", out)

    def test_healthy_status(self):
        out = render_report([SLOSnapshot("API", 0.999, 1000, 0)])
        self.assertIn("- **API**: healthy (0% of budget consumed).", out)

    def test_exhausted_status(self):
        out = render_report([SLOSnapshot("API", 0.999, 1000, 10)])
        self.assertIn("error budget exhausted", out)
        self.assertIn("1000% consumed", out)

    def test_nearly_exhausted_status(self):
        out = render_report([SLOSnapshot("API", 0.999, 10_000, 9)])
        self.assertIn("budget nearly exhausted", out)
        self.assertIn("90% consumed", out)

    def test_no_events_status_and_row(self):
        out = render_report([SLOSnapshot("API", 0.999, 0, 0)])
        self.assertIn("| API | 99.90% | n/a | n/a | n/a |", out)
        self.assertIn("no events recorded", out)

    def test_multiple_snapshots_order_preserved(self):
        out = render_report([
            SLOSnapshot("API", 0.999, 10_000, 5),
            SLOSnapshot("Worker", 0.99, 1000, 20),
        ])
        self.assertLess(out.index("| API |"), out.index("| Worker |"))

    def test_worst_first_sorts_by_budget_consumed(self):
        out = render_report([
            SLOSnapshot("API", 0.999, 10_000, 5),     # 50% consumed
            SLOSnapshot("Worker", 0.99, 1000, 20),    # 200% consumed
            SLOSnapshot("Web", 0.999, 10_000, 9),     # 90% consumed
        ], worst_first=True)
        self.assertLess(out.index("| Worker |"), out.index("| Web |"))
        self.assertLess(out.index("| Web |"), out.index("| API |"))
        # status lines follow the same order
        self.assertLess(out.index("**Worker**"), out.index("**Web**"))
        self.assertLess(out.index("**Web**"), out.index("**API**"))

    def test_worst_first_puts_no_events_last(self):
        out = render_report([
            SLOSnapshot("Idle", 0.99, 0, 0),
            SLOSnapshot("API", 0.999, 10_000, 5),
        ], worst_first=True)
        self.assertLess(out.index("| API |"), out.index("| Idle |"))

    def test_worst_first_default_off(self):
        out = render_report([
            SLOSnapshot("API", 0.999, 10_000, 5),
            SLOSnapshot("Worker", 0.99, 1000, 20),
        ])
        self.assertLess(out.index("| API |"), out.index("| Worker |"))

    def test_invalid_slo_rejected(self):
        with self.assertRaises(ValueError):
            render_report([SLOSnapshot("API", 1.5, 100, 1)])


class TestSnapshotSummary(unittest.TestCase):
    def test_healthy_summary_fields(self):
        s = snapshot_summary(SLOSnapshot("api", 0.999, 250000, 120, window_days=30))
        self.assertEqual(s["status"], "healthy")
        self.assertAlmostEqual(s["error_rate"], 0.00048)
        self.assertAlmostEqual(s["burn_rate"], 0.48)
        self.assertAlmostEqual(s["exhaustion_days"], 15.6)

    def test_no_events_has_null_metrics(self):
        s = snapshot_summary(SLOSnapshot("idle", 0.99, 0, 0))
        self.assertEqual(s["status"], "no_events")
        self.assertIsNone(s["error_rate"])
        self.assertIsNone(s["burn_rate"])
        self.assertIsNone(s["exhaustion_days"])

    def test_exhausted_has_no_projection(self):
        s = snapshot_summary(SLOSnapshot("api", 0.99, 1000, 20, window_days=30))
        self.assertEqual(s["status"], "exhausted")
        self.assertLessEqual(s["remaining_fraction"], 0)
        self.assertIsNone(s["exhaustion_days"])

    def test_no_window_has_no_projection(self):
        s = snapshot_summary(SLOSnapshot("api", 0.999, 250000, 120))
        self.assertIsNone(s["exhaustion_days"])

    def test_zero_burn_projects_none(self):
        s = snapshot_summary(SLOSnapshot("api", 0.999, 1000, 0, window_days=30))
        self.assertEqual(s["status"], "healthy")
        self.assertIsNone(s["exhaustion_days"])


class TestExhaustionProjection(unittest.TestCase):
    def test_healthy_line_projects_exhaustion(self):
        snap = SLOSnapshot("api", 0.999, 250000, 120, window_days=30)
        out = render_report([snap])
        self.assertIn("At current burn the budget exhausts in ~15.6 days.", out)

    def test_nearly_exhausted_line_projects_exhaustion(self):
        snap = SLOSnapshot("api", 0.995, 1200000, 5400, window_days=30)
        out = render_report([snap])
        self.assertIn("budget nearly exhausted", out)
        self.assertIn("At current burn the budget exhausts in ~3.0 days.", out)

    def test_zero_burn_notes_no_projection(self):
        snap = SLOSnapshot("api", 0.999, 1000, 0, window_days=30)
        out = render_report([snap])
        self.assertIn("Zero burn: no exhaustion projected.", out)

    def test_exhausted_line_unchanged_with_window(self):
        snap = SLOSnapshot("api", 0.99, 1000, 20, window_days=30)
        out = render_report([snap])
        self.assertIn("error budget exhausted", out)
        self.assertNotIn("At current burn", out)

    def test_no_window_keeps_plain_status_line(self):
        snap = SLOSnapshot("api", 0.999, 250000, 120)
        out = render_report([snap])
        self.assertNotIn("At current burn", out)


if __name__ == "__main__":
    unittest.main()
