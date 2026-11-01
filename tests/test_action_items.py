import unittest
from datetime import datetime, timedelta, timezone

from sre_toolkit.postmortem import (action_item_followup,
                                    format_action_item_followup,
                                    parse_action_item)

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=30)).isoformat()
FRESH = (NOW - timedelta(days=2)).isoformat()


class TestParseActionItem(unittest.TestCase):
    def test_string_is_open(self):
        self.assertEqual(parse_action_item("do the thing"), ("do the thing", False))

    def test_object_with_done_state(self):
        self.assertEqual(parse_action_item({"item": "x", "done": True}), ("x", True))
        self.assertEqual(parse_action_item({"task": "y"}), ("y", False))
        self.assertEqual(parse_action_item({"text": "z"}), ("z", False))

    def test_invalid_shapes_rejected(self):
        for bad in ("", {"item": ""}, {"done": "yes"}, {"item": "x", "bogus": 1}, 42):
            with self.assertRaises(ValueError, msg=repr(bad)):
                parse_action_item(bad)


class TestFollowup(unittest.TestCase):
    def test_open_items_grouped_per_incident(self):
        report = action_item_followup([
            {"title": "a", "resolved": FRESH,
             "action_items": ["open one", {"item": "done one", "done": True}]},
            {"title": "b", "resolved": FRESH, "action_items": [{"item": "shipped", "done": True}]},
        ], now=NOW)
        self.assertEqual(report["open_items_total"], 1)
        self.assertEqual(report["incidents_with_open_items"], 1)
        self.assertEqual(report["incidents"][0]["open_items"], ["open one"])

    def test_stale_when_resolved_long_ago_with_open_items(self):
        report = action_item_followup(
            [{"title": "old", "resolved": OLD, "action_items": ["never landed"]}], now=NOW)
        self.assertEqual(report["stale_incidents"], 1)
        self.assertTrue(report["incidents"][0]["stale"])
        self.assertEqual(report["incidents"][0]["days_since_resolved"], 30.0)

    def test_fresh_open_items_are_not_stale(self):
        report = action_item_followup(
            [{"title": "fresh", "resolved": FRESH, "action_items": ["soon"]}], now=NOW)
        self.assertEqual(report["stale_incidents"], 0)

    def test_unparseable_resolved_reports_unknown_age(self):
        report = action_item_followup(
            [{"title": "weird", "resolved": "a while back", "action_items": ["x"]}], now=NOW)
        self.assertIsNone(report["incidents"][0]["days_since_resolved"])
        self.assertFalse(report["incidents"][0]["stale"])

    def test_custom_stale_window(self):
        report = action_item_followup(
            [{"title": "a", "resolved": FRESH, "action_items": ["x"]}],
            now=NOW, stale_days=1)
        self.assertTrue(report["incidents"][0]["stale"])

    def test_incidents_without_open_items_omitted(self):
        report = action_item_followup([
            {"title": "clean", "resolved": OLD},
            {"title": "done", "resolved": OLD,
             "action_items": [{"item": "x", "done": True}]},
        ], now=NOW)
        self.assertEqual(report["incidents"], [])
        self.assertIn("All recorded action items are done.",
                      format_action_item_followup(report))

    def test_sorted_most_open_first(self):
        report = action_item_followup([
            {"title": "one", "resolved": FRESH, "action_items": ["a"]},
            {"title": "three", "resolved": FRESH, "action_items": ["a", "b", "c"]},
        ], now=NOW)
        self.assertEqual(report["incidents"][0]["title"], "three")


class TestFormatFollowup(unittest.TestCase):
    def test_renders_stale_flag_and_items(self):
        report = action_item_followup(
            [{"title": "old one", "resolved": OLD, "action_items": ["fix it"]}], now=NOW)
        text = format_action_item_followup(report)
        self.assertIn("1 open across 1 incidents", text)
        self.assertIn("STALE", text)
        self.assertIn("- [ ] fix it", text)


if __name__ == "__main__":
    unittest.main()
