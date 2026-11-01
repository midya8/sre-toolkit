import unittest

from sre_toolkit.burn_alerts import BurnRule, BurnSample, burn_rate, evaluate_rules

SLO = 0.999  # 0.1% budget


def sample(window_hours, total, bad):
    return BurnSample(window_hours=window_hours, total_events=total, bad_events=bad)


class TestBurnRate(unittest.TestCase):
    def test_no_errors_is_zero_burn(self):
        self.assertEqual(burn_rate(SLO, 10_000, 0), 0.0)

    def test_budget_pace_is_1x(self):
        # 0.1% of events bad = burning exactly at budget pace.
        self.assertAlmostEqual(burn_rate(SLO, 10_000, 10), 1.0)

    def test_fast_burn(self):
        self.assertAlmostEqual(burn_rate(SLO, 10_000, 144), 14.4)


class TestEvaluateRules(unittest.TestCase):
    def test_quiet_service_fires_nothing(self):
        samples = [sample(1.0, 10_000, 5), sample(5 / 60, 1_000, 0)]
        self.assertEqual(evaluate_rules(SLO, samples), [])

    def test_page_fires_when_both_windows_hot(self):
        # 14.4x burn on both the 1h and the 5m window.
        samples = [sample(1.0, 10_000, 144), sample(5 / 60, 1_000, 15)]
        firing = evaluate_rules(SLO, samples)
        # Only the page rule fires: the ticket rule's 6h/30m windows have no
        # usable samples here, so it is skipped by design.
        self.assertEqual([r.name for r in firing], ["page"])
        self.assertEqual(firing[0].severity, "critical")

    def test_blip_does_not_page(self):
        # 5m window hot but the 1h window calm: no alert at all.
        samples = [sample(1.0, 10_000, 5), sample(5 / 60, 1_000, 20)]
        self.assertEqual(evaluate_rules(SLO, samples), [])

    def test_slow_leak_tickets_without_paging(self):
        # 6x burn sustained over 6h and 30m, but under the 14.4x page bar.
        samples = [sample(6.0, 60_000, 360), sample(0.5, 5_000, 30)]
        firing = evaluate_rules(SLO, samples)
        self.assertEqual([r.name for r in firing], ["ticket"])

    def test_missing_windows_skip_rule(self):
        # Only a 1h sample: the page rule has no short window, so it is
        # skipped, and the ticket rule (6h/30m) has no usable window either.
        samples = [sample(1.0, 10_000, 500)]
        self.assertEqual(evaluate_rules(SLO, samples), [])

    def test_window_matching_tolerates_approximation(self):
        # A 55-minute sample still counts as "about 1h".
        samples = [sample(55 / 60, 10_000, 144), sample(4 / 60, 1_000, 15)]
        self.assertIn("page", [r.name for r in evaluate_rules(SLO, samples)])

    def test_custom_rules(self):
        rules = (BurnRule("watch", "medium", 2.0, 24.0, 1.0),)
        samples = [sample(24.0, 100_000, 200), sample(1.0, 10_000, 20)]
        self.assertEqual([r.name for r in evaluate_rules(SLO, samples, rules)], ["watch"])


if __name__ == "__main__":
    unittest.main()
