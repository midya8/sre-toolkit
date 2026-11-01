import unittest

from sre_toolkit.error_budget import (
    allowed_downtime_minutes,
    compute_error_budget,
    time_to_exhaustion_days,
)


class TestComputeErrorBudget(unittest.TestCase):
    def test_zero_bad_events_leaves_full_budget(self):
        budget = compute_error_budget(0.999, 1_000_000, 0)
        self.assertEqual(budget.consumed_fraction, 0.0)
        self.assertEqual(budget.remaining_fraction, 1.0)
        self.assertEqual(budget.burn_rate, 0.0)

    def test_exact_budget_consumption(self):
        # 0.1% budget over 10k events = 10 bad events exactly.
        budget = compute_error_budget(0.999, 10_000, 10)
        self.assertAlmostEqual(budget.consumed_fraction, 1.0)
        self.assertAlmostEqual(budget.remaining_fraction, 0.0)

    def test_double_budget_burns_at_2x(self):
        budget = compute_error_budget(0.999, 10_000, 20)
        self.assertAlmostEqual(budget.burn_rate, 2.0)
        self.assertAlmostEqual(budget.remaining_fraction, -1.0)

    def test_budget_fraction_matches_slo(self):
        budget = compute_error_budget(0.95, 1000, 10)
        self.assertAlmostEqual(budget.budget_fraction, 0.05)

    def test_rejects_invalid_slo_bounds(self):
        for slo in (0.0, 1.0, -0.5, 1.5):
            with self.assertRaises(ValueError):
                compute_error_budget(slo, 100, 1)

    def test_rejects_bad_event_counts(self):
        with self.assertRaises(ValueError):
            compute_error_budget(0.99, 0, 0)
        with self.assertRaises(ValueError):
            compute_error_budget(0.99, 100, 101)
        with self.assertRaises(ValueError):
            compute_error_budget(0.99, 100, -1)


class TestAllowedDowntime(unittest.TestCase):
    def test_99_9_percent_over_30_days(self):
        # 0.1% of 30 days = 43.2 minutes.
        self.assertAlmostEqual(allowed_downtime_minutes(0.999, 30), 43.2)

    def test_99_percent_over_one_day(self):
        self.assertAlmostEqual(allowed_downtime_minutes(0.99, 1), 14.4)

    def test_rejects_non_positive_window(self):
        with self.assertRaises(ValueError):
            allowed_downtime_minutes(0.99, 0)


class TestTimeToExhaustion(unittest.TestCase):
    def test_zero_burn_projects_nothing(self):
        budget = compute_error_budget(0.999, 10_000, 0)
        self.assertIsNone(time_to_exhaustion_days(budget, 30))

    def test_half_burned_mid_window_projects_window_end(self):
        budget = compute_error_budget(0.999, 10_000, 10)  # fully consumed
        self.assertAlmostEqual(time_to_exhaustion_days(budget, 30), 0.0)


if __name__ == "__main__":
    unittest.main()
