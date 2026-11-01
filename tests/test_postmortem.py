import unittest

from sre_toolkit.postmortem import Incident, render_postmortem


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
        incident = Incident(
            title="t", severity="low", started="s", detected="d", resolved="r",
            services=(), summary="s", impact="i", root_cause="rc",
        )
        text = render_postmortem(incident)
        self.assertIn("(no timeline entries recorded)", text)
        self.assertIn("(no action items recorded)", text)
        self.assertIn("**Services:** n/a", text)


if __name__ == "__main__":
    unittest.main()
