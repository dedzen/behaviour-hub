from datetime import date, datetime
import unittest

from nice_ui.pages.day_timeline import (
    TimelineBlock,
    TimelinePoint,
    color_for_activity,
    percent_into_day,
    render_day_timeline_html,
    seconds_into_day,
)


class DayTimelineViewHelpersTest(unittest.TestCase):
    def test_seconds_into_day_clamps_to_day_bounds(self):
        day = date(2026, 8, 1)

        self.assertEqual(seconds_into_day(datetime(2026, 7, 31, 23, 59), day), 0)
        self.assertEqual(seconds_into_day(datetime(2026, 8, 1, 12, 0), day), 43200)
        self.assertEqual(seconds_into_day(datetime(2026, 8, 2, 1, 0), day), 86400)

    def test_percent_into_day_maps_time_to_width(self):
        self.assertEqual(percent_into_day(datetime(2026, 8, 1, 6, 0), date(2026, 8, 1)), 25)

    def test_render_includes_separate_source_lanes_and_markers(self):
        html = render_day_timeline_html(
            day=date(2026, 8, 1),
            blocks=[
                TimelineBlock("embed", "Sleep", 0, 20, "#2563eb", "embed: Sleep", "inside", 1, 2),
                TimelineBlock("phone", "App", 10, 5, "#16a34a", "phone: App", "above", 3, 4),
            ],
            points=[
                TimelinePoint("phone", "Unlock", 11, "phone: Unlock", 5),
            ],
        )

        self.assertIn("embed", html)
        self.assertIn("phone", html)
        self.assertIn("Sleep", html)
        self.assertIn("Unlock", html)
        self.assertIn('data-event-ids="1,2"', html)
        self.assertIn('data-event-ids="5"', html)

    def test_activity_colors_are_stable(self):
        self.assertEqual(
            color_for_activity("embed", "Sleep"),
            color_for_activity("embed", "Sleep"),
        )


if __name__ == "__main__":
    unittest.main()
