import unittest
from datetime import datetime, timedelta, timezone

from sre_toolkit.burn_alerts import BurnRule, replay_rules

T0 = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)


def series(hot_idx, total=30000, hot_bad=900, quiet_bad=20, n=24):
    return [{"timestamp": (T0 + timedelta(minutes=5 * i)).isoformat(),
             "total": total, "bad": hot_bad if i in hot_idx else quiet_bad}
            for i in range(n)]


RULE = BurnRule("test", "high", 6.0, 1.0, 5.0 / 60.0)


class TestReplayValidation(unittest.TestCase):
    def test_bad_buckets_rejected(self):
        for buckets in (
            [],
            [{"total": 10, "bad": 1}],                       # no timestamp
            [{"timestamp": "soon", "total": 10, "bad": 1}],  # bad ts
            [{"timestamp": T0.isoformat(), "bad": 1}],       # no total
            [{"timestamp": T0.isoformat(), "total": 10, "bad": 11}],  # bad>total
            [{"timestamp": T0.isoformat(), "total": -5, "bad": 0}],
            ["not-an-object"],
        ):
            with self.assertRaises(ValueError, msg=repr(buckets)):
                replay_rules(0.999, buckets, rules=(RULE,))

    def test_naive_timestamp_assumed_utc(self):
        reports = replay_rules(0.999, [
            {"timestamp": "2026-10-31T20:00:00", "total": 100, "bad": 90},
        ], rules=(RULE,))
        self.assertEqual(reports[0]["intervals"][0]["start"].tzinfo, timezone.utc)

    def test_unsorted_buckets_sorted(self):
        buckets = series(set(), n=3)[::-1]
        reports = replay_rules(0.999, buckets, rules=(RULE,))
        self.assertEqual(reports[0]["firing_ticks"], 0)


class TestReplayFiring(unittest.TestCase):
    def test_quiet_series_never_fires(self):
        reports = replay_rules(0.999, series(set()), rules=(RULE,))
        self.assertEqual(reports[0]["firing_ticks"], 0)
        self.assertEqual(reports[0]["intervals"], [])

    def test_hot_streak_fires_during_it(self):
        reports = replay_rules(0.999, series(set(range(6, 12))), rules=(RULE,))
        report = reports[0]
        self.assertGreater(report["firing_ticks"], 0)
        interval = report["intervals"][0]
        self.assertGreaterEqual(interval["start"], T0 + timedelta(minutes=30))
        self.assertLessEqual(interval["end"], T0 + timedelta(minutes=70))

    def test_two_hot_streaks_make_two_intervals(self):
        reports = replay_rules(0.999, series({2, 3, 20, 21}, n=24, hot_bad=3000),
                               rules=(RULE,))
        intervals = reports[0]["intervals"]
        self.assertEqual(len(intervals), 2)
        self.assertLess(intervals[0]["end"], intervals[1]["start"])

    def test_window_excludes_buckets_outside_it(self):
        # One hot bucket long ago must not keep the 5m window firing.
        buckets = [{"timestamp": T0.isoformat(), "total": 100, "bad": 90}]
        buckets += [{"timestamp": (T0 + timedelta(minutes=5 * i)).isoformat(),
                     "total": 30000, "bad": 20} for i in range(1, 8)]
        reports = replay_rules(0.999, buckets, rules=(RULE,))
        report = reports[0]
        firing_at = [iv["start"] for iv in report["intervals"]]
        self.assertIn(T0, firing_at)
        self.assertEqual(report["intervals"][0]["ticks"], 1)

    def test_zero_total_window_not_firing(self):
        reports = replay_rules(0.999, [
            {"timestamp": T0.isoformat(), "total": 0, "bad": 0},
        ], rules=(RULE,))
        self.assertEqual(reports[0]["firing_ticks"], 0)

    def test_severity_sort_order(self):
        rules = (BurnRule("slow", "medium", 0.1, 1.0, 5 / 60),
                 BurnRule("fast", "critical", 0.1, 1.0, 5 / 60))
        reports = replay_rules(0.999, series(set(range(6, 12))), rules=rules)
        self.assertEqual(reports[0]["severity"], "critical")


if __name__ == "__main__":
    unittest.main()
