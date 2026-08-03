from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from timeline.api.timeline import Timeline
from timeline.api.timeline import parse_db_datetime
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Chunk, Event
from timeline.storage.repository import SQLiteRepository


class ClippedTimelineTest(unittest.TestCase):
    def test_parse_db_datetime_accepts_offset_and_naive_strings(self):
        self.assertEqual(
            parse_db_datetime("2026-08-01 09:00:00+03:00"),
            datetime(2026, 8, 1, 9, 0),
        )
        self.assertEqual(
            parse_db_datetime("2026-08-01 09:00:00"),
            datetime(2026, 8, 1, 9, 0),
        )

    def test_clips_chunk_that_started_before_query_range(self):
        with self._timeline() as timeline:
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 23, 55),
                datetime(2026, 8, 2, 8, 0),
            )

            df = timeline.day("2026-08-02").statistics.chunks.df

            self.assertEqual(df.height, 1)
            self.assertEqual(df["start_timestamp"][0], datetime(2026, 8, 2, 0, 0))
            self.assertEqual(df["end_timestamp"][0], datetime(2026, 8, 2, 8, 0))
            self.assertEqual(df["duration_seconds"][0], 8 * 3600)

    def test_clips_chunk_that_ends_after_query_range(self):
        with self._timeline() as timeline:
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 23, 55),
                datetime(2026, 8, 2, 8, 0),
            )

            df = timeline.day("2026-08-01").analytics.chunks.df

            self.assertEqual(df.height, 1)
            self.assertEqual(df["start_timestamp"][0], datetime(2026, 8, 1, 23, 55))
            self.assertEqual(df["end_timestamp"][0], datetime(2026, 8, 2, 0, 0))
            self.assertEqual(df["duration_seconds"][0], 5 * 60)

    def test_original_polars_chunk_view_keeps_persisted_interval(self):
        with self._timeline() as timeline:
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 23, 55),
                datetime(2026, 8, 2, 8, 0),
            )

            df = timeline.day("2026-08-01").to_polars()

            self.assertEqual(df.height, 1)
            self.assertEqual(df["start_timestamp"][0], datetime(2026, 8, 1, 23, 55))
            self.assertEqual(df["end_timestamp"][0], datetime(2026, 8, 2, 8, 0))
            self.assertEqual(df["duration_seconds"][0], 29100)

    def test_analytics_over_time_splits_chunks_across_days(self):
        with self._timeline() as timeline:
            self._insert_chunk(
                timeline.repo,
                datetime(2026, 8, 1, 23, 55),
                datetime(2026, 8, 2, 1, 0),
            )

            df = timeline.analytics.chunks.over_time("day", by=None)

            rows = {
                row["period"].date(): row["total_seconds"]
                for row in df.select(["period", "total_seconds"]).to_dicts()
            }
            self.assertEqual(rows[date(2026, 8, 1)], 5 * 60)
            self.assertEqual(rows[date(2026, 8, 2)], 60 * 60)

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
    ) -> None:
        start_event = Event(
            timestamp=start,
            device_source=DeviceSource.EMBED,
            event_kind=EventKind.INTERVAL_START,
            category="Body",
            name="Sleep",
        )
        end_event = Event(
            timestamp=end,
            device_source=DeviceSource.EMBED,
            event_kind=EventKind.INTERVAL_END,
            category="Body",
            name="Sleep",
        )
        repo.insert_event(start_event)
        repo.insert_event(end_event)
        repo._insert_chunk(
            Chunk(
                start_timestamp=start,
                end_timestamp=end,
                duration_seconds=int((end - start).total_seconds()),
                category="Body",
                name="Sleep",
                source=DeviceSource.EMBED,
                start_event_id=start_event.id, # type: ignore
                end_event_id=end_event.id, # type: ignore
            )
        )
        repo.commit()


if __name__ == "__main__":
    unittest.main()
