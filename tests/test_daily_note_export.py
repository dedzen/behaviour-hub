from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Chunk, Event
from timeline.export.daily_note import (
    build_daily_note_data,
    render_timeline_daily_note_markdown,
)
from timeline.storage.repository import SQLiteRepository


class DailyNoteExportTest(unittest.TestCase):
    def test_builds_daily_note_data_from_timeline(self):
        with self._timeline() as timeline:
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 0, 0),
                datetime(2026, 8, 1, 8, 0),
                DeviceSource.EMBED,
                "Body",
                "Sleep",
            )
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 9, 0),
                datetime(2026, 8, 1, 12, 0),
                DeviceSource.EMBED,
                "Work",
                "Working",
            )
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 12, 30),
                datetime(2026, 8, 1, 13, 0),
                DeviceSource.EMBED,
                "Food",
                "Eating",
            )
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 10, 0),
                datetime(2026, 8, 1, 11, 0),
                DeviceSource.PHONE,
                "Screen",
                "Screen on",
            )

            data = build_daily_note_data(
                timeline,
                date(2026, 8, 1),
                ["Working", "Eating"],
            )

            self.assertEqual(data.tracked_time, "11h 30m")
            self.assertEqual(data.active_screen_time, "1h")
            self.assertEqual(data.top_activity, "Working (3h)")
            self.assertEqual(data.important_activities, [
                "Working(1) - 3h | +100.0% | +100.0%",
                "Eating(1) - 30m | +100.0% | +100.0%",
            ])
            self.assertEqual(data.screen_time_intersections[0], "Working: 33.3%")
            self.assertEqual(data.validation_status, "Valid")
            self.assertEqual(data.extras["iso_date"], "2026-08-01")
            self.assertEqual(data.extras["iso_week"], "2026-W31")
            self.assertEqual(data.extras["iso_tracked_text_time"], "11 hours 30 minutes")
            self.assertEqual(data.extras["iso_screen_text_time"], "1 hour")
            self.assertEqual(data.extras["iso_sleep_time_text"], "8 hours")

    def test_renders_markdown_with_important_activities_and_intersection(self):
        with self._timeline() as timeline:
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 9, 0),
                datetime(2026, 8, 1, 10, 0),
                DeviceSource.EMBED,
                "Work",
                "Working",
            )
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 9, 15),
                datetime(2026, 8, 1, 9, 45),
                DeviceSource.PHONE,
                "Screen",
                "Screen on",
            )

            markdown = render_timeline_daily_note_markdown(
                timeline,
                "2026-08-01",
                ["Working"],
            )

            self.assertIn("date: 2026-08-01 #2026-08-04", markdown)
            self.assertIn("week: 2026-W31 #2026-W32", markdown)
            self.assertIn("tracked-time: 1 hour #5 hours 20 minutes", markdown)
            self.assertIn("screen-time: 30 minutes #5 hours 20 minutes", markdown)
            self.assertIn("sleep-time: 0 seconds #8 hours 03 minutes", markdown)
            self.assertIn('top-activity: "Working (1h)"', markdown)
            self.assertIn("## Important Activities", markdown)
            self.assertIn("- Working(1) - 1h | +100.0% | +100.0%", markdown)
            self.assertIn("## Screen Time Intersection", markdown)
            self.assertIn("- Working: 50.0%", markdown)
            self.assertIn("- Validation status: Valid", markdown)
            self.assertNotIn("## Trends", markdown)
            self.assertNotIn("category", markdown)
            self.assertNotIn("screen share", markdown)

    def test_validation_status_reports_validator_errors(self):
        with self._timeline() as timeline:
            timeline.repo.insert_event(
                Event(
                    timestamp=datetime(2026, 8, 1, 9, 0),
                    device_source=DeviceSource.EMBED,
                    event_kind=EventKind.INTERVAL_START,
                    category=None,
                    name="Working",
                )
            )
            timeline.repo.commit()

            data = build_daily_note_data(
                timeline,
                "2026-08-01",
                ["Working"],
            )

            self.assertEqual(data.validation_status, "Invalid: 1 errors, 1 warnings")

    def test_trends_use_important_activity_time_percentages(self):
        with self._timeline() as timeline:
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 7, 31, 9, 0),
                datetime(2026, 7, 31, 10, 0),
                DeviceSource.EMBED,
                "Work",
                "Working",
            )
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 7, 31, 9, 0),
                datetime(2026, 7, 31, 9, 15),
                DeviceSource.PHONE,
                "Screen",
                "Screen on",
            )
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 9, 0),
                datetime(2026, 8, 1, 10, 0),
                DeviceSource.EMBED,
                "Work",
                "Working",
            )
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 9, 0),
                datetime(2026, 8, 1, 9, 30),
                DeviceSource.PHONE,
                "Screen",
                "Screen on",
            )

            data = build_daily_note_data(
                timeline,
                "2026-08-01",
                ["Working"],
            )

            self.assertEqual(data.important_activities, [
                "Working(1) - 1h | +0.0% | +0.0%",
            ])

    @contextmanager
    def _timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()
            try:
                yield Timeline(repo)
            finally:
                repo.close()

    def _insert_chunk(
        self,
        repo: SQLiteRepository,
        start: datetime,
        end: datetime,
        source: DeviceSource,
        category: str,
        name: str,
    ) -> None:
        start_event = Event(
            timestamp=start,
            device_source=source,
            event_kind=EventKind.INTERVAL_START,
            category=category,
            name=name,
        )
        end_event = Event(
            timestamp=end,
            device_source=source,
            event_kind=EventKind.INTERVAL_END,
            category=category,
            name=name,
        )
        repo.insert_event(start_event)
        repo.insert_event(end_event)
        repo._insert_chunk(
            Chunk(
                start_timestamp=start,
                end_timestamp=end,
                duration_seconds=int((end - start).total_seconds()),
                category=category,
                name=name,
                source=source,
                start_event_id=start_event.id, # type: ignore[arg-type]
                end_event_id=end_event.id, # type: ignore[arg-type]
            )
        )
        repo.commit()

if __name__ == "__main__":
    unittest.main()
