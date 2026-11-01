import unittest
from datetime import timedelta

from sre_toolkit.postmortem import Incident, render_postmortem, response_metrics


def sample_incident() -> Incident:
    return Incident(
        title="Checkout latency spike",
        severity="high",
        started="2026-10-30 14:05 UTC",
        detected="2026-10-30 14:12 UTC",
        resolved="2026-10-30 15:40 UTC",
        services=("checkout", "payments"),
        summary="Checkout p99 latency rose from 300ms to 4s for 95 minutes.",
        impact="12% of checkout attempts timed out; no data loss.",
        root_cause="A connection-pool limit change left workers starved of DB connections.",
        timeline=(
            ("14:05", "Deploy of pool config change begins"),
            ("14:12", "Latency alert fires, on-call paged"),
            ("15:40", "Rollback completes, latency recovers"),
        ),
        action_items=("Add pool-saturation dashboard", "Gate config deploys on latency canary"),
    )


def unparseable_incident() -> Incident:
    return Incident(
        title="t", severity="low", started="s", detected="d", resolved="r",
        services=(), summary="s", impact="i", root_cause="rc",
    )


class TestRenderPostmortem(unittest.TestCase):
    def test_contains_all_sections(self):
        text = render_postmortem(sample_incident())
        for section in ("## Summary", "## Impact", "## Root cause", "## Timeline", "## Action items"):
            self.assertIn(section, text)

    def test_header_fields(self):
        text = render_postmortem(sample_incident())
        self.assertIn("# Postmortem: Checkout latency spike", text)
        self.assertIn("**Severity:** high", text)
        self.assertIn("checkout, payments", text)

    def test_timeline_entries_rendered(self):
        text = render_postmortem(sample_incident())
        self.assertIn("- **14:12** - Latency alert fires, on-call paged", text)

    def test_action_items_are_checkboxes(self):
        text = render_postmortem(sample_incident())
        self.assertIn("- [ ] Add pool-saturation dashboard", text)

    def test_empty_timeline_and_actions_have_placeholders(self):
        text = render_postmortem(unparseable_incident())
        self.assertIn("(no timeline entries recorded)", text)
        self.assertIn("(no action items recorded)", text)
        self.assertIn("**Services:** n/a", text)

    def test_response_metrics_section_rendered(self):
        text = render_postmortem(sample_incident())
        self.assertIn("## Response metrics", text)
        self.assertIn("- **Time to detect:** 7 minutes", text)
        self.assertIn("- **Time to resolve:** 1 hour 28 minutes", text)
        self.assertIn("- **Total duration:** 1 hour 35 minutes", text)

    def test_response_metrics_section_skipped_when_unparseable(self):
        text = render_postmortem(unparseable_incident())
        self.assertNotIn("## Response metrics", text)


class TestResponseMetrics(unittest.TestCase):
    def test_values(self):
        metrics = response_metrics(sample_incident())
        self.assertEqual(metrics.time_to_detect, timedelta(minutes=7))
        self.assertEqual(metrics.time_to_resolve, timedelta(minutes=88))
        self.assertEqual(metrics.total_duration, timedelta(minutes=95))

    def test_iso_timestamps_with_z(self):
        incident = Incident(
            title="t", severity="low",
            started="2026-10-30T14:05:00Z",
            detected="2026-10-30T14:12:30Z",
            resolved="2026-10-30T14:47:00Z",
            services=(), summary="s", impact="i", root_cause="rc",
        )
        metrics = response_metrics(incident)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.time_to_detect, timedelta(minutes=7, seconds=30))
        self.assertEqual(metrics.time_to_resolve, timedelta(minutes=34, seconds=30))

    def test_unparseable_returns_none(self):
        self.assertIsNone(response_metrics(unparseable_incident()))

    def test_out_of_order_returns_none(self):
        incident = Incident(
            title="t", severity="low",
            started="2026-10-30 14:12 UTC",
            detected="2026-10-30 14:05 UTC",
            resolved="2026-10-30 15:40 UTC",
            services=(), summary="s", impact="i", root_cause="rc",
        )
        self.assertIsNone(response_metrics(incident))

    def test_mixed_naive_and_aware_returns_none(self):
        incident = Incident(
            title="t", severity="low",
            started="2026-10-30 14:05",
            detected="2026-10-30 14:12 UTC",
            resolved="2026-10-30 15:40 UTC",
            services=(), summary="s", impact="i", root_cause="rc",
        )
        self.assertIsNone(response_metrics(incident))


if __name__ == "__main__":
    unittest.main()
