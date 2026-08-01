from datetime import datetime
import tempfile
import unittest
from pathlib import Path

from nice_ui.pages.events import event_matches_search, parse_event_timestamp
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Event
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


if __name__ == "__main__":
    unittest.main()
