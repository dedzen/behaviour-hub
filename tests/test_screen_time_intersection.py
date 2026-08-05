from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from timeline.analytics.screen_time_intersection import (
    active_screen_intersection,
    active_screen_intersection_over_time,
)
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Chunk, Event
from timeline.storage.repository import SQLiteRepository


class ScreenTimeIntersectionTest(unittest.TestCase):
    def test_calculates_active_screen_overlap_with_selected_activity(self):
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

            df = active_screen_intersection(timeline, ["Working"])

            self.assertEqual(df.height, 1)
            row = df.to_dicts()[0]
            self.assertEqual(row["category"], "Work")
            self.assertEqual(row["name"], "Working")
            self.assertEqual(row["activity_seconds"], 3600)
            self.assertEqual(row["screen_seconds"], 1800)
            self.assertEqual(row["activity_without_screen_seconds"], 1800)
            self.assertEqual(row["screen_total_seconds"], 1800)
            self.assertEqual(row["activity_screen_percent"], 50.0)

    def test_uses_clipped_query_window_for_activity_and_screen_chunks(self):
        with self._timeline() as timeline:
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 7, 31, 23, 55),
                datetime(2026, 8, 1, 0, 20),
                DeviceSource.EMBED,
                "Food",
                "Eating",
            )
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 0, 10),
                datetime(2026, 8, 1, 0, 30),
                DeviceSource.PHONE,
                "Screen",
                "Screen on",
            )

            df = active_screen_intersection(timeline.day("2026-08-01"), ["Eating"])

            row = df.to_dicts()[0]
            self.assertEqual(row["activity_seconds"], 20 * 60)
            self.assertEqual(row["screen_seconds"], 10 * 60)

    def test_ignores_sidebar_source_and_activity_filters(self):
        with self._timeline() as timeline:
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 9, 0),
                datetime(2026, 8, 1, 9, 30),
                DeviceSource.EMBED,
                "Food",
                "Eating",
            )
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 9, 0),
                datetime(2026, 8, 1, 9, 30),
                DeviceSource.PHONE,
                "Screen",
                "Screen on",
            )

            filtered = timeline.source(DeviceSource.EMBED).activity("Working")
            df = active_screen_intersection(filtered, ["Eating"])

            self.assertEqual(df.height, 1)
            self.assertEqual(df["screen_seconds"][0], 30 * 60)

    def test_calculates_screen_share_over_time_by_period(self):
        with self._timeline() as timeline:
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 23, 30),
                datetime(2026, 8, 2, 0, 30),
                DeviceSource.EMBED,
                "Work",
                "Working",
            )
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 23, 45),
                datetime(2026, 8, 2, 0, 15),
                DeviceSource.PHONE,
                "Screen",
                "Screen on",
            )

            df = active_screen_intersection_over_time(timeline, ["Working"], "day")

            rows = {
                row["period"].date(): row
                for row in df.to_dicts()
            }
            self.assertEqual(rows[datetime(2026, 8, 1).date()]["activity_seconds"], 30 * 60)
            self.assertEqual(rows[datetime(2026, 8, 1).date()]["screen_seconds"], 15 * 60)
            self.assertEqual(rows[datetime(2026, 8, 1).date()]["activity_screen_percent"], 50.0)
            self.assertEqual(rows[datetime(2026, 8, 2).date()]["activity_seconds"], 30 * 60)
            self.assertEqual(rows[datetime(2026, 8, 2).date()]["screen_seconds"], 15 * 60)
            self.assertEqual(rows[datetime(2026, 8, 2).date()]["activity_screen_percent"], 50.0)

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
