from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from nicegui.client import Client
from nicegui.page import page
from nice_ui.app import MainDashboard
from nice_ui.pages.filter_panel import (
    FilterPanel,
    FilterState,
    previous_date_range,
    resolved_date_range,
)
from nice_ui.responsive import (
    AppShell,
    NAVIGATION,
    RESPONSIVE_CSS,
    VIEWPORT,
    desktop_navigation_html,
    responsive_chart_options,
    visible_columns_expression,
)
from nice_ui.runtime import DashboardRuntime, DashboardSession


class ResponsiveUiHelpersTest(unittest.TestCase):
    def test_navigation_keeps_stable_routes_for_future_pwa_entry_points(self):
        self.assertEqual(
            [(item.key, item.path) for item in NAVIGATION],
            [
                ("Main", "/"),
                ("Calendar", "/calendar"),
                ("Goals", "/goals"),
                ("Import/Export", "/import-export"),
            ],
        )
        self.assertIn("viewport-fit=cover", VIEWPORT)
        tablet_rules = RESPONSIVE_CSS.split("@media (max-width: 1023px)", 1)[1]
        self.assertIn(".bh-desktop-only", tablet_rules)

    def test_navigation_uses_native_links_on_desktop_and_mobile(self):
        client = Client(page(f"/navigation-links-{uuid4().hex}"))
        with client:
            AppShell("Main")

        hrefs = [
            element._props["href"]
            for element in client.elements.values()
            if "href" in element._props
        ]
        self.assertEqual(hrefs.count("/"), 1)
        self.assertEqual(hrefs.count("/calendar"), 1)
        self.assertEqual(hrefs.count("/goals"), 1)
        self.assertEqual(hrefs.count("/import-export"), 1)
        desktop = desktop_navigation_html("Calendar")
        self.assertIn('href="/"', desktop)
        self.assertIn('href="/calendar"', desktop)
        self.assertIn('href="/goals"', desktop)
        self.assertIn('href="/import-export"', desktop)
        self.assertIn("bh-desktop-nav-item-active", desktop)
        self.assertIn('aria-current="page"', desktop)
        client.delete()

    def test_visible_columns_switch_at_the_quasar_mobile_breakpoint(self):
        expression = visible_columns_expression(
            ["activity", "total"],
            ["activity", "sessions", "total"],
        )

        self.assertIn("$q.screen.lt.md", expression)
        self.assertIn("['activity','total']", expression)
        self.assertIn("['activity','sessions','total']", expression)

    def test_chart_options_add_mobile_media_without_replacing_desktop_options(self):
        options = {
            "legend": {"right": 8},
            "series": [{"type": "bar", "data": [1]}],
        }

        result = responsive_chart_options(options)

        self.assertIs(result, options)
        self.assertEqual(result["legend"], {"right": 8})
        self.assertEqual(result["media"][0]["query"], {"maxWidth": 600})
        self.assertIn("grid", result["media"][0]["option"])

    def test_pie_chart_uses_a_compact_mobile_layout(self):
        options = {"series": [{"type": "pie", "data": [1]}]}

        result = responsive_chart_options(options, pie=True)

        mobile_series = result["media"][0]["option"]["series"][0]
        self.assertEqual(mobile_series["center"], ["50%", "42%"])

    def test_filter_summary_only_shows_active_constraints(self):
        panel = FilterPanel.__new__(FilterPanel)
        panel.state = FilterState(
            preset="Last 7 days",
            sources={"embed", "phone"},
            activities={"Focus", "Exercise"},
            min_duration=300,
            max_duration=3600,
        )

        self.assertEqual(
            panel.summary_labels(),
            ["Last 7 days", "Embed + Phone", "2 activities", "5m–1h"],
        )

    def test_filter_ranges_are_half_open_and_custom_end_is_inclusive(self):
        start, end = resolved_date_range(FilterState(), today=date(2026, 8, 10))
        self.assertEqual(start, datetime(2026, 8, 10))
        self.assertEqual(end, datetime(2026, 8, 11))

        start, end = resolved_date_range(
            FilterState(
                preset="Custom...",
                start=date(2026, 8, 1),
                end=date(2026, 8, 3),
            )
        )
        self.assertEqual(start, datetime(2026, 8, 1))
        self.assertEqual(end, datetime(2026, 8, 4))
        self.assertEqual(
            previous_date_range(start, end),
            (datetime(2026, 7, 29), datetime(2026, 8, 1)),
        )

    def test_desktop_dashboard_content_stretches_to_available_width(self):
        with TemporaryDirectory() as directory:
            runtime = DashboardRuntime(Path(directory) / "timeline.db")
            runtime.initialize()
            client = Client(page(f"/responsive-width-{uuid4().hex}"))
            with client:
                dashboard = MainDashboard(DashboardSession(runtime, client))

            classes = dashboard.dashboard_content._classes
            self.assertIn("w-full", classes)
            self.assertIn("self-stretch", classes)
            self.assertIn("max-w-none", classes)
            client.delete()


if __name__ == "__main__":
    unittest.main()
