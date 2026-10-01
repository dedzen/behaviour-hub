from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nice_ui.pages.overview import delta_text, overview_metrics
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.interval_builder import IntervalBuilder
from timeline.domain.models import Event
from timeline.storage.repository import SQLiteRepository


class OverviewMetricsTest(unittest.TestCase):
    def test_source_filter_accepts_one_shot_iterables(self):
        with TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()
            timeline = Timeline(repo).source(source for source in [DeviceSource.EMBED])
            self.assertEqual(timeline.query.sources, frozenset({DeviceSource.EMBED}))
            repo.close()

    def test_screen_time_is_kept_separate_from_selected_activity_source(self):
        with TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()
            events = [
                Event(datetime(2026, 8, 1, 9), DeviceSource.EMBED, EventKind.INTERVAL_START, "Work", "Focus"),
                Event(datetime(2026, 8, 1, 10), DeviceSource.EMBED, EventKind.INTERVAL_END, "Work", "Focus"),
                Event(datetime(2026, 8, 1, 9, 15), DeviceSource.PHONE, EventKind.INTERVAL_START, "Screen", "Screen on"),
                Event(datetime(2026, 8, 1, 9, 45), DeviceSource.PHONE, EventKind.INTERVAL_END, "Screen", "Screen on"),
            ]
            for event in events:
                repo.insert_event(event)
            chunks, _ = IntervalBuilder.build(events)
            repo.replace_chunks(chunks)
            repo.commit()

            timeline = Timeline(repo).day(date(2026, 8, 1)).source(DeviceSource.EMBED)
            metrics = overview_metrics(timeline)

            self.assertEqual(metrics.tracked_seconds, 3600)
            self.assertEqual(metrics.sessions, 1)
            self.assertEqual(metrics.screen_seconds, 1800)
            repo.close()

    def test_delta_text_handles_missing_and_zero_comparisons(self):
        self.assertEqual(delta_text(10, 5, available=True), "↑ 100% vs previous period")
        self.assertEqual(delta_text(10, 0, available=True), "No prior data")
        self.assertEqual(delta_text(10, 5, available=False), "No comparison")


if __name__ == "__main__":
    unittest.main()
