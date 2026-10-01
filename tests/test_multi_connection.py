from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from nicegui.client import Client
from nicegui.page import page
from nice_ui.app import MainDashboard
from nice_ui.pages.day_timeline import DayTimelineView
from nice_ui.pages.events import EventEditor
from nice_ui.runtime import ChangeBus, DashboardSession, DataChange, DashboardRuntime
from timeline.api.timeline import Timeline
from timeline.application.mutations import TimelineMutationService
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import DayMarker, Event
from timeline.storage.errors import ConcurrentModificationError
from timeline.storage.repository import SQLiteRepository


class _FakeClient:
    def __init__(self):
        self.is_deleted = False
        self.delete_handlers = []

    def on_delete(self, callback):
        self.delete_handlers.append(callback)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class MultiConnectionPersistenceTest(unittest.TestCase):
    def test_existing_schema_is_migrated_with_initial_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "timeline.db"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    device_source TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    category TEXT,
                    name TEXT
                );
                CREATE TABLE day_markers (
                    id INTEGER PRIMARY KEY,
                    day TEXT NOT NULL UNIQUE,
                    habits_json TEXT NOT NULL DEFAULT '{}',
                    people_json TEXT NOT NULL DEFAULT '[]',
                    quick_note_markdown TEXT NOT NULL DEFAULT '',
                    mood REAL
                );
                INSERT INTO events VALUES (
                    1, '2026-08-01 09:00:00', 'embed', 'point', 'Work', 'Focus'
                );
                INSERT INTO day_markers VALUES (1, '2026-08-01', '{}', '[]', '', NULL);
                """
            )
            connection.close()

            with SQLiteRepository(database) as repo:
                repo.ensure_schema()
                event = repo.get(Event, 1)
                marker = repo.get_day_marker(date(2026, 8, 1))

            self.assertEqual(event.revision, 1)
            self.assertEqual(marker.revision, 1)

    def test_stale_event_update_and_delete_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "timeline.db"
            service = TimelineMutationService(database)
            service.initialize()
            with SQLiteRepository(database) as repo:
                event = Event(
                    timestamp=datetime(2026, 8, 1, 9),
                    device_source=DeviceSource.EMBED,
                    event_kind=EventKind.POINT,
                    category="Work",
                    name="Focus",
                )
                repo.insert_event(event)

            with SQLiteRepository(database) as first, SQLiteRepository(database) as second:
                first_copy = first.get(Event, event.id)
                stale_copy = second.get(Event, event.id)

            first_copy.name = "Deep work"
            service.update_event(first_copy, first_copy.revision)
            stale_copy.name = "Shallow work"

            with self.assertRaises(ConcurrentModificationError):
                service.update_event(stale_copy, stale_copy.revision)
            with self.assertRaises(ConcurrentModificationError):
                service.delete_event(stale_copy.id, stale_copy.revision)

    def test_event_edit_rolls_back_when_chunk_rebuild_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "timeline.db"
            service = TimelineMutationService(database)
            service.initialize()
            with SQLiteRepository(database) as repo:
                event = Event(
                    timestamp=datetime(2026, 8, 1, 9),
                    device_source=DeviceSource.EMBED,
                    event_kind=EventKind.POINT,
                    category="Work",
                    name="Original",
                )
                repo.insert_event(event)

            event.name = "Uncommitted"
            with patch.object(service, "_rebuild", side_effect=RuntimeError("failed")):
                with self.assertRaises(RuntimeError):
                    service.update_event(event, event.revision)

            with SQLiteRepository(database) as repo:
                persisted = repo.get(Event, event.id)
            self.assertEqual(persisted.name, "Original")
            self.assertEqual(persisted.revision, 1)

    def test_stale_day_marker_save_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "timeline.db"
            service = TimelineMutationService(database)
            service.initialize()
            original = DayMarker(date(2026, 8, 1), {}, [], "first", None)
            service.save_day_marker(original, 0)

            first = DayMarker(date(2026, 8, 1), {}, [], "second", None, revision=1)
            stale = DayMarker(date(2026, 8, 1), {}, [], "stale", None, revision=1)
            service.save_day_marker(first, first.revision)

            with self.assertRaises(ConcurrentModificationError):
                service.save_day_marker(stale, stale.revision)


class ConnectionLifecycleTest(unittest.TestCase):
    def test_sessions_own_independent_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = DashboardRuntime(Path(directory) / "timeline.db")
            runtime.initialize()
            first_client = _FakeClient()
            second_client = _FakeClient()
            first = DashboardSession(runtime, first_client)  # type: ignore[arg-type]
            second = DashboardSession(runtime, second_client)  # type: ignore[arg-type]

            self.assertIsNot(first.repo, second.repo)
            first.close()
            self.assertEqual(second.repo.load_events(), [])
            with self.assertRaises(sqlite3.ProgrammingError):
                first.repo.load_events()
            second.close()

    def test_change_bus_broadcasts_and_unsubscribes_per_client(self):
        bus = ChangeBus()
        first_client = _FakeClient()
        second_client = _FakeClient()
        received = [[], []]
        first_token = bus.subscribe(first_client, received[0].append)  # type: ignore[arg-type]
        bus.subscribe(second_client, received[1].append)  # type: ignore[arg-type]
        change = DataChange(events_changed=True)

        bus.publish(change)
        bus.unsubscribe(first_token)
        bus.publish(DataChange(marker_days=frozenset({date(2026, 8, 1)})))

        self.assertEqual(received[0], [change])
        self.assertEqual(len(received[1]), 2)

    def test_two_main_dashboards_construct_and_refresh_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = DashboardRuntime(Path(directory) / "timeline.db")
            runtime.initialize()
            clients = []
            dashboards = []
            for _ in range(2):
                client = Client(page(f"/multi-main-{uuid4().hex}"))
                clients.append(client)
                with client:
                    session = DashboardSession(runtime, client)
                    dashboard = MainDashboard(session)
                    session.subscribe(dashboard.database_changed)
                    dashboards.append(dashboard)

            dashboards[0].filters.state.preset = "Today"
            runtime.changes.publish(DataChange(events_changed=True))

            self.assertEqual(dashboards[0].filters.state.preset, "Today")
            self.assertEqual(dashboards[1].filters.state.preset, "All time")
            self.assertIsNot(dashboards[0].events, dashboards[1].events)
            for client in clients:
                client.delete()


class RuntimePublicationTest(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_publishes_only_after_successful_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = DashboardRuntime(Path(directory) / "timeline.db")
            client = _FakeClient()
            received = []
            runtime.changes.subscribe(client, received.append)  # type: ignore[arg-type]

            async def immediately(callback):
                return callback()

            with patch("nice_ui.runtime.run.io_bound", side_effect=immediately):
                runtime.service.rebuild_chunks = lambda: (_ for _ in ()).throw(
                    RuntimeError("failed")
                )
                with self.assertRaises(RuntimeError):
                    await runtime.rebuild_chunks()
                self.assertEqual(received, [])

                from timeline.application.mutations import MutationResult

                runtime.service.rebuild_chunks = lambda: MutationResult("done")
                result = await runtime.rebuild_chunks()

            self.assertEqual(result.message, "done")
            self.assertEqual(received, [DataChange(events_changed=True)])


class DirtyFormRefreshTest(unittest.TestCase):
    def test_dirty_event_editor_is_preserved_and_marked_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "timeline.db"
            repo = SQLiteRepository(database)
            repo.ensure_schema()
            event = Event(
                timestamp=datetime(2026, 8, 1, 9),
                device_source=DeviceSource.EMBED,
                event_kind=EventKind.POINT,
                category="Work",
                name="Original",
            )
            repo.insert_event(event)
            repo.commit()
            client = Client(page(f"/dirty-event-{uuid4().hex}"))
            with client:
                editor = EventEditor()
                editor.open(Timeline(repo), event.id)
                editor.name.set_value("Unsaved local value")
                editor.dirty = True

            with SQLiteRepository(database) as other:
                changed = other.get(Event, event.id)
                changed.name = "Remote value"
                other.update(changed)

            with client:
                editor.database_changed()

            self.assertTrue(editor.stale)
            self.assertEqual(editor.name.value, "Unsaved local value")
            client.delete()
            repo.close()

    def test_dirty_marker_form_is_preserved_and_marked_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "timeline.db"
            repo = SQLiteRepository(database)
            repo.ensure_schema()
            marker = DayMarker(date(2026, 8, 1), {}, [], "Original", None)
            repo.upsert_day_marker(marker)
            repo.commit()
            client = Client(page(f"/dirty-marker-{uuid4().hex}"))
            with client:
                view = DayTimelineView()
                view.update(Timeline(repo).day(date(2026, 8, 1)))
                view.quick_note_input.set_value("Unsaved local value")
                view.marker_dirty = True

            with SQLiteRepository(database) as other:
                changed = other.get_day_marker(date(2026, 8, 1))
                changed.quick_note_markdown = "Remote value"
                other.upsert_day_marker(changed)

            with client:
                view.database_changed(
                    events_changed=False,
                    marker_days=frozenset({date(2026, 8, 1)}),
                )

            self.assertTrue(view.marker_stale)
            self.assertEqual(view.quick_note_input.value, "Unsaved local value")
            client.delete()
            repo.close()


if __name__ == "__main__":
    unittest.main()
