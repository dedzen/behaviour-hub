from datetime import datetime
import tempfile
import unittest
from pathlib import Path

from nice_ui.pages.events import (
    event_matches_search,
    parse_event_timestamp,
    rebuild_chunks_for_repo,
)
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Event
from timeline.api.query import Query
from timeline.storage.repository import SQLiteRepository


class EventBrowserHelpersTest(unittest.TestCase):
    def test_parse_event_timestamp_accepts_iso_date_time(self):
        parsed = parse_event_timestamp("2026-08-01 09:30:15")

        self.assertEqual(parsed, datetime(2026, 8, 1, 9, 30, 15))

    def test_parse_event_timestamp_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            parse_event_timestamp("next tuesday")

    def test_event_matches_search_checks_visible_fields(self):
        event = Event(
            id=42,
            timestamp=datetime(2026, 8, 1, 9, 30),
            device_source=DeviceSource.PC,
            event_kind=EventKind.INTERVAL_START,
            category="Work",
            name="Deep focus",
        )

        self.assertTrue(event_matches_search(event, "focus"))
        self.assertTrue(event_matches_search(event, "pc"))
        self.assertTrue(event_matches_search(event, "42"))
        self.assertFalse(event_matches_search(event, "phone"))


class EventBrowserPersistenceTest(unittest.TestCase):
    def test_event_edits_round_trip_through_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()

            event = Event(
                timestamp=datetime(2026, 8, 1, 9, 30),
                device_source=DeviceSource.EMBED,
                event_kind=EventKind.POINT,
                category="Old",
                name="Before",
            )
            repo.insert_event(event)
            repo.commit()

            event.timestamp = parse_event_timestamp("2026-08-01T10:45:00")
            event.device_source = DeviceSource.PHONE
            event.event_kind = EventKind.INTERVAL_END
            event.category = "New"
            event.name = "After"
            repo.update(event)
            repo.commit()

            loaded = repo.get(Event, event.id) #type: ignore

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.timestamp, datetime(2026, 8, 1, 10, 45)) #type: ignore
            self.assertEqual(loaded.device_source, DeviceSource.PHONE) #type: ignore
            self.assertEqual(loaded.event_kind, EventKind.INTERVAL_END) #type: ignore
            self.assertEqual(loaded.category, "New") #type: ignore
            self.assertEqual(loaded.name, "After") #type: ignore
            repo.close()

    def test_rebuild_chunks_for_repo_refreshes_generated_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()

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
            repo.commit()

            warnings = rebuild_chunks_for_repo(repo)

            chunks = repo.load_chunks()
            self.assertEqual(warnings, [])
            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0].duration_seconds, 3600)
            repo.close()

    def test_insert_event_deduplicates_across_device_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()

            first = Event(
                timestamp=datetime(2026, 8, 1, 9, 30),
                device_source=DeviceSource.EMBED,
                event_kind=EventKind.POINT,
                category="Work",
                name="Focus",
            )
            second = Event(
                timestamp=datetime(2026, 8, 1, 9, 30),
                device_source=DeviceSource.PHONE,
                event_kind=EventKind.POINT,
                category="Work",
                name="Focus",
            )

            inserted_first = repo.insert_event(first)
            inserted_second = repo.insert_event(second)
            repo.commit()

            events = repo.load_events()
            self.assertTrue(inserted_first)
            self.assertFalse(inserted_second)
            self.assertEqual(len(events), 1)
            self.assertEqual(second.id, first.id)
            repo.close()

    def test_update_event_merges_into_existing_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()

            first = Event(
                timestamp=datetime(2026, 8, 1, 9, 30),
                device_source=DeviceSource.EMBED,
                event_kind=EventKind.POINT,
                category="Work",
                name="Focus",
            )
            second = Event(
                timestamp=datetime(2026, 8, 1, 10, 0),
                device_source=DeviceSource.PHONE,
                event_kind=EventKind.POINT,
                category="Relax",
                name="Scroll",
            )
            repo.insert_event(first)
            repo.insert_event(second)
            repo.commit()

            second.timestamp = first.timestamp
            second.event_kind = first.event_kind
            second.category = first.category
            second.name = first.name
            repo.update(second)
            repo.commit()

            events = repo.load_events()
            self.assertEqual(len(events), 1)
            self.assertEqual(second.id, first.id)
            repo.close()

    def test_deduplicate_events_cleans_legacy_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()

            repo.conn.execute(
                """
                INSERT INTO events(timestamp, device_source, event_kind, category, name)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("2026-08-01 09:30:00", "embed", "point", "Work", "Focus"),
            )
            repo.conn.execute(
                """
                INSERT INTO events(timestamp, device_source, event_kind, category, name)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("2026-08-01 09:30:00", "phone", "point", "Work", "Focus"),
            )
            repo.commit()

            removed = repo.deduplicate_events()
            repo.commit()

            events = repo.load_events()
            self.assertEqual(removed, 1)
            self.assertEqual(len(events), 1)
            repo.close()

    def test_load_events_filters_by_device_source_column(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "timeline.db")
            repo.ensure_schema()

            embed = Event(
                timestamp=datetime(2026, 8, 1, 9, 30),
                device_source=DeviceSource.EMBED,
                event_kind=EventKind.POINT,
                category="Work",
                name="Focus",
            )
            phone = Event(
                timestamp=datetime(2026, 8, 1, 10, 0),
                device_source=DeviceSource.PHONE,
                event_kind=EventKind.POINT,
                category="Phone",
                name="Screen active",
            )
            repo.insert_event(embed)
            repo.insert_event(phone)
            repo.commit()

            events = repo.load_events(Query(sources=frozenset({DeviceSource.PHONE})))

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].device_source, DeviceSource.PHONE)
            repo.close()


if __name__ == "__main__":
    unittest.main()
