import unittest

from sre_toolkit.slo_doc import SLODefinition, render_slo_doc

DEF = SLODefinition(
    name="Checkout availability",
    service="checkout-api",
    target=0.999,
    window_days=30,
    sli="Share of requests without a 5xx.",
    description="Revenue path.",
    alert_thresholds=("page at 14.4x burn over 1h + 5m",),
)


class TestRenderSloDoc(unittest.TestCase):
    def test_header_fields(self):
        out = render_slo_doc(DEF)
        self.assertIn("# SLO: Checkout availability", out)
        self.assertIn("- **Service:** checkout-api", out)
        self.assertIn("- **Target:** 99.90%", out)
        self.assertIn("- **Window:** 30 days (rolling)", out)
        self.assertIn("- **SLI:** Share of requests without a 5xx.", out)

    def test_error_budget_section(self):
        out = render_slo_doc(DEF)
        self.assertIn("Budget fraction: 0.100%", out)
        self.assertIn("43.2 minutes of full outage per 30-day window", out)

    def test_description_included(self):
        self.assertIn("Revenue path.", render_slo_doc(DEF))

    def test_description_omitted_when_empty(self):
        d = SLODefinition("n", "svc", 0.99, 7, "sli")
        self.assertNotIn("\n\n\n", render_slo_doc(d))

    def test_alert_thresholds_listed(self):
        self.assertIn("- page at 14.4x burn over 1h + 5m", render_slo_doc(DEF))

    def test_no_thresholds_placeholder(self):
        d = SLODefinition("n", "svc", 0.99, 7, "sli")
        self.assertIn("_No alert thresholds defined._", render_slo_doc(d))

    def test_invalid_target_rejected(self):
        with self.assertRaises(ValueError):
            render_slo_doc(SLODefinition("n", "svc", 1.5, 30, "sli"))

    def test_invalid_window_rejected(self):
        with self.assertRaises(ValueError):
            render_slo_doc(SLODefinition("n", "svc", 0.99, 0, "sli"))


if __name__ == "__main__":
    unittest.main()
