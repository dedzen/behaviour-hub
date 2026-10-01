from datetime import date
import tempfile
from pathlib import Path
import unittest

from timeline.export.to_markdown import (
    DailyNoteData,
    MarkdownRenderOptions,
    daily_note_values,
    render_daily_note_markdown,
)


class MarkdownExportTest(unittest.TestCase):
    def test_renders_daily_note_with_defaults(self):
        markdown = render_daily_note_markdown(
            DailyNoteData(
                date=date(2026, 8, 1),
                tracked_time="8h",
                active_screen_time="2h",
                important_activities=[
                    {"activity": "Working", "total": "4h"},
                    "Eating - 45m",
                ],
                screen_time_intersections=[
                    {"activity": "Working", "screen": "1h", "share": "25%"},
                ],
                validation_status="Clean",
            )
        )

        self.assertIn("date: 2026-08-01", markdown)
        self.assertIn("week: 2026-W31", markdown)
        self.assertIn("- Tracked time: 8h", markdown)
        self.assertIn("- Active screen time: 2h", markdown)
        self.assertIn("- Working: total: 4h", markdown)
        self.assertIn("- Eating - 45m", markdown)
        self.assertIn("- Working: screen: 1h, share: 25%", markdown)
        self.assertIn("- Validation status: Clean", markdown)

    def test_supports_mapping_input_overrides_and_custom_template(self):
        markdown = render_daily_note_markdown(
            {
                "date": "2026-08-01",
                "tracked_time": "4h",
                "extras": {"mood": "steady"},
            },
            template="Daily {date}: {tracked_time}; mood={mood}; custom={custom}",
            overrides={"custom": "yes"},
        )

        self.assertEqual(markdown, "Daily 2026-08-01: 4h; mood=steady; custom=yes\n")

    def test_supports_custom_options_and_value_formatters(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / "template.md"
            template.write_text("{{date}}\n{{important_activities}}\n{{missing}}\n", encoding="utf-8")

            markdown = render_daily_note_markdown(
                DailyNoteData(
                    date=date(2026, 8, 1),
                    important_activities=["Working", "Eating"],
                ),
                options=MarkdownRenderOptions(
                    template_path=template,
                    bullet="*",
                    missing_value="n/a",
                    value_formatters={"date": lambda value: f"day={value}"},
                ),
            )

            self.assertEqual(markdown, "day=2026-08-01\n* Working\n* Eating\nn/a\n")

    def test_daily_note_values_exposes_extras(self):
        values = daily_note_values(
            DailyNoteData(
                date=date(2026, 8, 1),
                extras={"custom_metric": "42"},
            )
        )

        self.assertEqual(values["custom_metric"], "42")
        self.assertEqual(values["iso_date"], "2026-08-01")
        self.assertEqual(values["iso_week"], "2026-W31")


if __name__ == "__main__":
    unittest.main()
