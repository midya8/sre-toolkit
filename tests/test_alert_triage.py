import unittest

from sre_toolkit.alert_triage import (
    rules_from_dict,
    Alert, classify_severity, dedupe, dedupe_key, duplicate_counts, group_by_service,
    inhibit_by_critical, triage,
)


class TestRulesFromDict(unittest.TestCase):
    def test_builds_rules_most_severe_first(self):
        rules = rules_from_dict({"medium": ["flaky"], "critical": ["sev1"]})
        self.assertEqual(rules, (("critical", ("sev1",)), ("medium", ("flaky",))))

    def test_unknown_severity_rejected(self):
        with self.assertRaises(ValueError):
            rules_from_dict({"urgent": ["now"]})

    def test_empty_and_malformed_rejected(self):
        for bad in ({}, {"critical": []}, {"critical": "page"}, {"critical": [""]},
                    {"critical": ["ok", 3]}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                rules_from_dict(bad)

    def test_custom_rules_drive_classification(self):
        rules = rules_from_dict({"critical": ["sev1"]})
        self.assertEqual(classify_severity("SEV1 on checkout", rules), "critical")
        self.assertEqual(classify_severity("page: everything down", rules), "low")


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


class TestInhibitByCritical(unittest.TestCase):
    ALERTS = [
        Alert("a1", "api", "Outage", severity="critical"),
        Alert("a2", "api", "Error rate elevated", severity="high"),
        Alert("a3", "api", "Disk warning", severity="medium"),
        Alert("a4", "web", "Weekly report", severity="low"),
    ]

    def test_lower_severities_suppressed_on_critical_service(self):
        kept, inhibited = inhibit_by_critical(self.ALERTS)
        self.assertEqual([a.alert_id for a in kept], ["a1", "a4"])
        self.assertEqual([a.alert_id for a in inhibited], ["a2", "a3"])

    def test_nothing_inhibited_without_critical(self):
        alerts = [Alert("a1", "api", "Warning", severity="medium"),
                  Alert("a2", "db", "Slow", severity="low")]
        kept, inhibited = inhibit_by_critical(alerts)
        self.assertEqual(kept, alerts)
        self.assertEqual(inhibited, [])

    def test_critical_on_other_service_does_not_inhibit(self):
        alerts = [Alert("a1", "db", "Outage", severity="critical"),
                  Alert("a2", "api", "Error rate elevated", severity="high")]
        kept, inhibited = inhibit_by_critical(alerts)
        self.assertEqual(len(kept), 2)
        self.assertEqual(inhibited, [])

    def test_empty_input(self):
        self.assertEqual(inhibit_by_critical([]), ([], []))


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
