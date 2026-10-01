from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from nice_ui.pages.day_timeline import (
    TimelineBlock,
    TimelinePoint,
    color_for_activity,
    find_chunk_by_event_ids,
    percent_into_day,
    remove_chunk_source_events,
    render_day_timeline_html,
    seconds_into_day,
)
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Chunk, Event
from timeline.storage.repository import SQLiteRepository


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
        self.assertIn("--source-count:2", html)
        self.assertIn("@media (max-width: 1023px)", html)

    def test_activity_colors_are_stable(self):
        self.assertEqual(
            color_for_activity("embed", "Sleep"),
            color_for_activity("embed", "Sleep"),
        )

    def test_find_chunk_by_event_ids_matches_generated_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()
            start, end = self._insert_chunk(repo)

            chunk = find_chunk_by_event_ids(repo, [start.id, end.id]) # type: ignore[list-item]

            self.assertIsNotNone(chunk)
            self.assertEqual(chunk.start_event_id, start.id) # type: ignore[union-attr]
            self.assertEqual(chunk.end_event_id, end.id) # type: ignore[union-attr]
            repo.close()

    def test_remove_chunk_source_events_deletes_events_and_rebuilds_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()
            start, end = self._insert_chunk(repo)

            warnings = remove_chunk_source_events(repo, [start.id, end.id]) # type: ignore[list-item]

            self.assertEqual(warnings, [])
            self.assertEqual(repo.load_events(), [])
            self.assertEqual(repo.load_chunks(), [])
            repo.close()

    def _insert_chunk(self, repo: SQLiteRepository) -> tuple[Event, Event]:
        start = Event(
            timestamp=datetime(2026, 8, 1, 9, 0),
            device_source=DeviceSource.EMBED,
            event_kind=EventKind.INTERVAL_START,
            category="Work",
            name="Focus",
        )
        end = Event(
            timestamp=datetime(2026, 8, 1, 10, 0),
            device_source=DeviceSource.EMBED,
            event_kind=EventKind.INTERVAL_END,
            category="Work",
            name="Focus",
        )
        repo.insert_event(start)
        repo.insert_event(end)
        repo._insert_chunk(
            Chunk(
                start_timestamp=start.timestamp,
                end_timestamp=end.timestamp,
                duration_seconds=3600,
                category="Work",
                name="Focus",
                source=DeviceSource.EMBED,
                start_event_id=start.id, # type: ignore[arg-type]
                end_event_id=end.id, # type: ignore[arg-type]
            )
        )
        repo.commit()
        return start, end


if __name__ == "__main__":
    unittest.main()
