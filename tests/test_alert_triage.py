import unittest

from sre_toolkit.alert_triage import (
    Alert, classify_severity, dedupe, dedupe_key, duplicate_counts, group_by_service, triage,
)


class TestClassifySeverity(unittest.TestCase):
    def test_critical_keywords_win(self):
        self.assertEqual(classify_severity("Database outage in us-east"), "critical")

    def test_high_keywords(self):
        self.assertEqual(classify_severity("Elevated error rate on checkout"), "high")

    def test_medium_keywords(self):
        self.assertEqual(classify_severity("Disk usage warning on node-3"), "medium")

    def test_unmatched_is_low(self):
        self.assertEqual(classify_severity("Weekly report ready"), "low")

    def test_case_insensitive(self):
        self.assertEqual(classify_severity("API DOWN"), "critical")


class TestDedupe(unittest.TestCase):
    def test_duplicates_collapse_first_wins(self):
        alerts = [
            Alert("a1", "api", "Latency high"),
            Alert("a2", "api", "latency   high"),
            Alert("a3", "db", "Latency high"),
        ]
        unique = dedupe(alerts)
        self.assertEqual([a.alert_id for a in unique], ["a1", "a3"])

    def test_empty_input(self):
        self.assertEqual(dedupe([]), [])


class TestDuplicateCounts(unittest.TestCase):
    def test_counts_match_dedupe_survivors(self):
        alerts = [
            Alert("a1", "api", "Latency high"),
            Alert("a2", "api", "latency   high"),
            Alert("a3", "db", "Latency high"),
        ]
        counts = duplicate_counts(alerts)
        self.assertEqual(counts[dedupe_key(alerts[0])], 2)
        self.assertEqual(counts[dedupe_key(alerts[2])], 1)
        self.assertEqual(set(counts), {dedupe_key(a) for a in dedupe(alerts)})

    def test_unique_alerts_count_one(self):
        alerts = [Alert("a1", "api", "Outage"), Alert("a2", "db", "Warning")]
        counts = duplicate_counts(alerts)
        self.assertTrue(all(n == 1 for n in counts.values()))

    def test_empty_input(self):
        self.assertEqual(duplicate_counts([]), {})


class TestTriage(unittest.TestCase):
    def test_sorted_by_severity_then_service(self):
        alerts = [
            Alert("a1", "web", "Weekly report ready"),
            Alert("a2", "api", "Service down"),
            Alert("a3", "db", "Error rate elevated"),
        ]
        result = triage(alerts)
        self.assertEqual([a.severity for a in result], ["critical", "high", "low"])
        self.assertEqual(result[0].alert_id, "a2")

    def test_explicit_severity_kept(self):
        alerts = [Alert("a1", "api", "Anything", severity="critical")]
        self.assertEqual(triage(alerts)[0].severity, "critical")

    def test_unknown_explicit_severity_reclassified(self):
        alerts = [Alert("a1", "api", "Service down", severity="weird")]
        self.assertEqual(triage(alerts)[0].severity, "critical")

    def test_dedupe_within_triage(self):
        alerts = [
            Alert("a1", "api", "Outage"),
            Alert("a2", "api", "outage"),
        ]
        self.assertEqual(len(triage(alerts)), 1)


class TestGroupByService(unittest.TestCase):
    def test_groups_preserve_order(self):
        alerts = [
            Alert("a1", "api", "x"),
            Alert("a2", "db", "y"),
            Alert("a3", "api", "z"),
        ]
        grouped = group_by_service(alerts)
        self.assertEqual([a.alert_id for a in grouped["api"]], ["a1", "a3"])
        self.assertEqual([a.alert_id for a in grouped["db"]], ["a2"])


if __name__ == "__main__":
    unittest.main()
