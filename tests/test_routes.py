import unittest

from sre_toolkit.alert_triage import (Alert, load_routes, owner_rollup,
                                      route_owner)


def alert(service, severity, alert_id="a1"):
    return Alert(alert_id=alert_id, service=service,
                 summary="something broke", severity=severity)


class TestLoadRoutes(unittest.TestCase):
    def test_happy_path(self):
        routes = load_routes({"routes": {"checkout": "payments"},
                              "default": "sre"})
        self.assertEqual(route_owner(routes, "checkout"), "payments")
        self.assertEqual(route_owner(routes, "unknown-svc"), "sre")

    def test_default_owner_fallback(self):
        routes = load_routes({"routes": {}})
        self.assertEqual(route_owner(routes, "anything"), "unrouted")

    def test_exact_match_only(self):
        routes = load_routes({"routes": {"checkout": "payments"}})
        self.assertEqual(route_owner(routes, "checkout-api"), "unrouted")

    def test_bad_specs_rejected(self):
        for bad in (["not-a-dict"],
                    {"routes": "nope"},
                    {"routes": {"svc": 42}},
                    {"routes": {"": "team"}},
                    {"routes": {}, "default": ""},
                    {"routes": {}, "default": 7}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                load_routes(bad)


class TestOwnerRollup(unittest.TestCase):
    def test_worst_severity_first_then_busiest(self):
        routes = load_routes({"routes": {"checkout": "payments",
                                         "gateway": "platform"},
                              "default": "sre"})
        alerts = [
            alert("checkout", "low", "1"),
            alert("checkout", "critical", "2"),
            alert("gateway", "high", "3"),
            alert("misc", "low", "4"),
            alert("misc", "low", "5"),
        ]
        rows = owner_rollup(alerts, routes)
        self.assertEqual([r["owner"] for r in rows],
                         ["payments", "platform", "sre"])
        self.assertEqual(rows[0]["alerts"], 2)
        self.assertEqual(rows[0]["worst_severity"], "critical")
        self.assertEqual(rows[0]["by_severity"], {"low": 1, "critical": 1})
        self.assertEqual(rows[2]["alerts"], 2)  # busiest last by severity

    def test_empty_alerts_empty_rollup(self):
        routes = load_routes({"routes": {}})
        self.assertEqual(owner_rollup([], routes), [])


if __name__ == "__main__":
    unittest.main()
