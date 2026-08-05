from contextlib import contextmanager
from datetime import datetime
import tempfile
import unittest
from pathlib import Path

from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.interval_builder import IntervalBuilder
from timeline.domain.models import Chunk, Event
from timeline.storage.repository import SQLiteRepository
from timeline.validation.validator import Validator


def event(
    source: DeviceSource,
    kind: EventKind,
    hour: int,
    name: str,
) -> Event:
    return Event(
        timestamp=datetime(2026, 8, 1, hour),
        device_source=source,
        event_kind=kind,
        category="Activity",
        name=name,
    )


class ValidatorMultiSourceTest(unittest.TestCase):
    def test_allows_overlapping_intervals_from_different_sources(self):
        with self._repo() as repo:
            self._insert_events(
                repo,
                [
                    event(DeviceSource.PC, EventKind.INTERVAL_START, 9, "Code"),
                    event(DeviceSource.PHONE, EventKind.INTERVAL_START, 9, "Walk"),
                    event(DeviceSource.PC, EventKind.INTERVAL_END, 10, "Code"),
                    event(DeviceSource.PHONE, EventKind.INTERVAL_END, 10, "Walk"),
                ],
            )

            report = Validator(repo).validate()

            self.assertEqual(report.issues, [])

    def test_interleaved_sources_do_not_close_or_mismatch_each_other(self):
        with self._repo() as repo:
            self._insert_events(
                repo,
                [
                    event(DeviceSource.PC, EventKind.INTERVAL_START, 9, "Code"),
                    event(DeviceSource.PHONE, EventKind.INTERVAL_START, 10, "Screen on"),
                    event(DeviceSource.PHONE, EventKind.INTERVAL_END, 11, "Screen on"),
                    event(DeviceSource.PC, EventKind.INTERVAL_END, 12, "Code"),
                ],
            )

            report = Validator(repo).validate()

            self.assertEqual(report.issues, [])

    def test_rejects_overlapping_events_from_same_source(self):
        with self._repo() as repo:
            self._insert_events(
                repo,
                [
                    event(DeviceSource.PC, EventKind.INTERVAL_START, 9, "Code"),
                    event(DeviceSource.PC, EventKind.INTERVAL_START, 10, "Meeting"),
                    event(DeviceSource.PC, EventKind.INTERVAL_END, 11, "Code"),
                ],
            )

            report = Validator(repo).validate()

            self.assertTrue(any("still active on pc" in issue.message for issue in report.issues))

    def test_mismatched_end_does_not_close_active_interval(self):
        with self._repo() as repo:
            self._insert_events(
                repo,
                [
                    event(DeviceSource.PC, EventKind.INTERVAL_START, 9, "Code"),
                    event(DeviceSource.PC, EventKind.INTERVAL_END, 10, "Meeting"),
                    event(DeviceSource.PC, EventKind.INTERVAL_END, 11, "Code"),
                ],
            )

            report = Validator(repo).validate()

            self.assertTrue(any("Activity mismatch" in issue.message for issue in report.issues))
            self.assertFalse(any("still open on pc" in issue.message for issue in report.issues))

    def test_allows_overlapping_chunks_from_different_sources(self):
        with self._repo() as repo:
            events = self._insert_events(
                repo,
                [
                    event(DeviceSource.PC, EventKind.INTERVAL_START, 9, "Code"),
                    event(DeviceSource.PHONE, EventKind.INTERVAL_START, 9, "Walk"),
                    event(DeviceSource.PC, EventKind.INTERVAL_END, 10, "Code"),
                    event(DeviceSource.PHONE, EventKind.INTERVAL_END, 10, "Walk"),
                ],
            )
            chunks, warnings = IntervalBuilder.build(events)
            repo.replace_chunks(chunks)
            repo.commit()

            report = Validator(repo).validate()

            self.assertEqual(warnings, [])
            self.assertEqual(report.issues, [])

    def test_interleaved_chunk_sources_do_not_overlap_each_other(self):
        with self._repo() as repo:
            events = self._insert_events(
                repo,
                [
                    event(DeviceSource.PC, EventKind.POINT, 9, "Start code"),
                    event(DeviceSource.PHONE, EventKind.POINT, 10, "Start phone"),
                    event(DeviceSource.PC, EventKind.POINT, 12, "End code"),
                    event(DeviceSource.PHONE, EventKind.POINT, 11, "End phone"),
                ],
            )
            repo.replace_chunks(
                [
                    Chunk(
                        start_timestamp=datetime(2026, 8, 1, 9),
                        end_timestamp=datetime(2026, 8, 1, 12),
                        duration_seconds=3 * 3600,
                        category="Activity",
                        name="Code",
                        source=DeviceSource.PC,
                        start_event_id=events[0].id,
                        end_event_id=events[2].id,
                    ),
                    Chunk(
                        start_timestamp=datetime(2026, 8, 1, 10),
                        end_timestamp=datetime(2026, 8, 1, 11),
                        duration_seconds=3600,
                        category="Activity",
                        name="Phone",
                        source=DeviceSource.PHONE,
                        start_event_id=events[1].id,
                        end_event_id=events[3].id,
                    ),
                ]
            )
            repo.commit()

            report = Validator(repo).validate()

            self.assertEqual(report.issues, [])

    def test_rejects_overlapping_chunks_from_same_source(self):
        with self._repo() as repo:
            events = self._insert_events(
                repo,
                [
                    event(DeviceSource.PC, EventKind.POINT, 9, "Start code"),
                    event(DeviceSource.PC, EventKind.POINT, 11, "End code"),
                    event(DeviceSource.PC, EventKind.POINT, 10, "Start meeting"),
                    event(DeviceSource.PC, EventKind.POINT, 12, "End meeting"),
                ],
            )
            repo.replace_chunks(
                [
                    Chunk(
                        start_timestamp=datetime(2026, 8, 1, 9),
                        end_timestamp=datetime(2026, 8, 1, 11),
                        duration_seconds=7200,
                        category="Activity",
                        name="Code",
                        source=DeviceSource.PC,
                        start_event_id=events[0].id,
                        end_event_id=events[1].id,
                    ),
                    Chunk(
                        start_timestamp=datetime(2026, 8, 1, 10),
                        end_timestamp=datetime(2026, 8, 1, 12),
                        duration_seconds=7200,
                        category="Activity",
                        name="Meeting",
                        source=DeviceSource.PC,
                        start_event_id=events[2].id,
                        end_event_id=events[3].id,
                    ),
                ]
            )
            repo.commit()

            report = Validator(repo).validate()

            self.assertTrue(any("overlaps previous chunk on pc" in issue.message for issue in report.issues))

    @contextmanager
    def _repo(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()
            try:
                yield repo
            finally:
                repo.close()

    def _insert_events(self, repo: SQLiteRepository, events: list[Event]) -> list[Event]:
        for item in events:
            repo.insert_event(item)
        repo.commit()
        return events


if __name__ == "__main__":
    unittest.main()
