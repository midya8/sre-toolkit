import unittest

from sre_toolkit.report import SLOSnapshot, render_report


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

    def test_invalid_slo_rejected(self):
        with self.assertRaises(ValueError):
            render_report([SLOSnapshot("API", 1.5, 100, 1)])


if __name__ == "__main__":
    unittest.main()
