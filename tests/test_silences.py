import unittest
from datetime import datetime, timedelta, timezone

from sre_toolkit.alert_triage import Alert
from sre_toolkit.silences import (Silence, apply_silences, load_silences,
                                  silence_from_dict)

FUTURE = "2999-01-01T00:00:00Z"
PAST = "2000-01-01T00:00:00Z"


def alert(service="web", summary="Service down", severity="critical"):
    return Alert(alert_id="a1", service=service, summary=summary, severity=severity)


class TestSilenceFromDict(unittest.TestCase):
    def test_valid_minimal(self):
        s = silence_from_dict({"service": "web", "reason": "r", "until": FUTURE})
        self.assertEqual(s.service, "web")
        self.assertEqual(s.reason, "r")
        self.assertIsNotNone(s.until.tzinfo)

    def test_unknown_keys_rejected(self):
        with self.assertRaises(ValueError):
            silence_from_dict({"service": "web", "reason": "r", "until": FUTURE,
                               "bogus": 1})

    def test_reason_required(self):
        with self.assertRaises(ValueError):
            silence_from_dict({"service": "web", "until": FUTURE})

    def test_until_required_and_parseable(self):
        with self.assertRaises(ValueError):
            silence_from_dict({"service": "web", "reason": "r"})
        with self.assertRaises(ValueError):
            silence_from_dict({"service": "web", "reason": "r", "until": "soon"})

    def test_severity_must_be_known(self):
        with self.assertRaises(ValueError):
            silence_from_dict({"severity": "page", "reason": "r", "until": FUTURE})

    def test_at_least_one_matcher_required(self):
        with self.assertRaises(ValueError):
            silence_from_dict({"reason": "r", "until": FUTURE})

    def test_naive_until_assumed_utc(self):
        s = silence_from_dict({"service": "web", "reason": "r",
                               "until": "2999-01-01T00:00:00"})
        self.assertEqual(s.until.tzinfo, timezone.utc)

    def test_load_silences_requires_a_list(self):
        with self.assertRaises(ValueError):
            load_silences({"service": "web"})
        self.assertEqual(len(load_silences(
            [{"service": "web", "reason": "r", "until": FUTURE}])), 1)


class TestMatching(unittest.TestCase):
    def test_all_set_matchers_must_match(self):
        s = silence_from_dict({"service": "web", "severity": "critical",
                               "reason": "r", "until": FUTURE})
        self.assertTrue(s.matches(alert()))
        self.assertFalse(s.matches(alert(severity="low")))
        self.assertFalse(s.matches(alert(service="api")))

    def test_contains_is_case_insensitive_substring(self):
        s = silence_from_dict({"contains": "WEEKLY report", "reason": "r",
                               "until": FUTURE})
        self.assertTrue(s.matches(alert(summary="Weekly report ready")))
        self.assertFalse(s.matches(alert(summary="Latency high")))

    def test_expired_silence_is_inactive(self):
        s = silence_from_dict({"service": "web", "reason": "r", "until": PAST})
        self.assertFalse(s.is_active(datetime.now(timezone.utc)))


class TestApplySilences(unittest.TestCase):
    def test_splits_kept_and_silenced_with_reason(self):
        silences = load_silences([
            {"service": "cache", "reason": "decom", "until": FUTURE}])
        alerts = [alert(service="cache", summary="Memory warning", severity="medium"),
                  alert(service="api", summary="Service down")]
        kept, silenced = apply_silences(alerts, silences)
        self.assertEqual([a.service for a in kept], ["api"])
        self.assertEqual(len(silenced), 1)
        self.assertEqual(silenced[0][1].reason, "decom")

    def test_first_matching_silence_wins(self):
        silences = load_silences([
            {"service": "web", "reason": "first", "until": FUTURE},
            {"service": "web", "reason": "second", "until": FUTURE}])
        _, silenced = apply_silences([alert()], silences)
        self.assertEqual(silenced[0][1].reason, "first")

    def test_expired_silences_match_nothing(self):
        silences = load_silences([
            {"service": "web", "reason": "old", "until": PAST}])
        kept, silenced = apply_silences([alert()], silences)
        self.assertEqual(len(kept), 1)
        self.assertEqual(silenced, [])

    def test_explicit_now_is_used(self):
        until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        silences = load_silences([{"service": "web", "reason": "r", "until": until}])
        later = datetime.now(timezone.utc) + timedelta(hours=2)
        kept, _ = apply_silences([alert()], silences, now=later)
        self.assertEqual(len(kept), 1)


if __name__ == "__main__":
    unittest.main()
