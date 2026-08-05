from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from nice_ui.pages.day_timeline import (
    format_people_text,
    habit_values_for_day,
    month_habit_names,
    parse_mood_value,
    parse_people_text,
)
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Chunk, DayMarker, Event
from timeline.storage.repository import SQLiteRepository
from timeline.validation.validator import Validator


class DayMarkerTest(unittest.TestCase):
    def test_day_marker_round_trips_through_repository(self):
        with self._repo() as repo:
            marker = repo.upsert_day_marker(
                DayMarker(
                    day=date(2026, 8, 1),
                    habits={"exercise": True, "alcohol": False},
                    people=["Alice", "Bob"],
                    quick_note_markdown="**Good day**",
                    mood=7.5,
                )
            )
            repo.commit()

            loaded = repo.get_day_marker("2026-08-01")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.id, marker.id) # type: ignore[union-attr]
            self.assertEqual(loaded.habits, {"alcohol": False, "exercise": True}) # type: ignore[union-attr]
            self.assertEqual(loaded.people, ["Alice", "Bob"]) # type: ignore[union-attr]
            self.assertEqual(loaded.quick_note_markdown, "**Good day**") # type: ignore[union-attr]
            self.assertEqual(loaded.mood, 7.5) # type: ignore[union-attr]

    def test_upsert_updates_existing_day_marker(self):
        with self._repo() as repo:
            repo.upsert_day_marker(
                DayMarker(
                    day=date(2026, 8, 1),
                    habits={"exercise": False},
                    people=[],
                    quick_note_markdown="old",
                    mood=None,
                )
            )
            repo.upsert_day_marker(
                DayMarker(
                    day=date(2026, 8, 1),
                    habits={"exercise": True},
                    people=["Alice"],
                    quick_note_markdown="new",
                    mood=6,
                )
            )
            repo.commit()

            markers = repo.load_day_markers()

            self.assertEqual(len(markers), 1)
            self.assertEqual(markers[0].habits, {"exercise": True})
            self.assertEqual(markers[0].people, ["Alice"])
            self.assertEqual(markers[0].quick_note_markdown, "new")
            self.assertEqual(markers[0].mood, 6)

    def test_load_and_delete_day_markers(self):
        with self._repo() as repo:
            repo.upsert_day_marker(DayMarker(date(2026, 8, 1), {}, [], "", None))
            repo.upsert_day_marker(DayMarker(date(2026, 8, 2), {}, [], "", None))
            repo.upsert_day_marker(DayMarker(date(2026, 8, 3), {}, [], "", None))
            repo.commit()

            markers = repo.load_day_markers(start="2026-08-02", end="2026-08-03")
            repo.delete_day_marker("2026-08-02")
            repo.commit()

            self.assertEqual([marker.day for marker in markers], [date(2026, 8, 2), date(2026, 8, 3)])
            self.assertIsNone(repo.get_day_marker(date(2026, 8, 2)))

    def test_timeline_day_picture_combines_marker_and_clipped_metrics(self):
        with self._repo() as repo:
            marker = repo.upsert_day_marker(
                DayMarker(
                    day=date(2026, 8, 1),
                    habits={"exercise": True},
                    people=["Alice"],
                    quick_note_markdown="note",
                    mood=8,
                )
            )
            self._insert_chunk(
                repo,
                datetime(2026, 8, 1, 0, 0),
                datetime(2026, 8, 1, 8, 0),
                DeviceSource.EMBED,
                "Body",
                "Sleep",
            )
            self._insert_chunk(
                repo,
                datetime(2026, 8, 1, 9, 0),
                datetime(2026, 8, 1, 11, 0),
                DeviceSource.EMBED,
                "Work",
                "Working",
            )
            self._insert_chunk(
                repo,
                datetime(2026, 8, 1, 12, 0),
                datetime(2026, 8, 1, 12, 30),
                DeviceSource.EMBED,
                "Food",
                "Eating",
            )
            self._insert_chunk(
                repo,
                datetime(2026, 8, 1, 9, 30),
                datetime(2026, 8, 1, 10, 0),
                DeviceSource.PHONE,
                "Screen",
                "Screen on",
            )
            repo.commit()

            picture = Timeline(repo).day_picture("2026-08-01")

            self.assertEqual(picture.day, date(2026, 8, 1))
            self.assertEqual(picture.marker, marker)
            self.assertEqual(picture.tracked_seconds, 10 * 3600 + 30 * 60)
            self.assertEqual(picture.active_screen_seconds, 30 * 60)
            self.assertEqual(picture.sleep_seconds, 8 * 3600)
            self.assertEqual(picture.top_activity, "Working")
            self.assertIn("Working", picture.activity_summary["name"].to_list())
            intersections = {
                row["name"]: row
                for row in picture.screen_intersection.to_dicts()
            }
            self.assertEqual(intersections["Working"]["screen_seconds"], 30 * 60)
            self.assertEqual(intersections["Working"]["activity_screen_percent"], 25.0)
            self.assertEqual(intersections["Eating"]["screen_seconds"], 0)
            self.assertEqual(intersections["Sleep"]["screen_seconds"], 0)

    def test_validator_reports_malformed_day_markers(self):
        with self._repo() as repo:
            repo.conn.execute(
                """
                INSERT INTO day_markers(
                    day,
                    habits_json,
                    people_json,
                    quick_note_markdown,
                    mood
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "not-a-day",
                    '{"exercise": "yes"}',
                    '["Alice", 123]',
                    "",
                    None,
                ),
            )
            repo.commit()

            report = Validator(repo).validate()

            self.assertTrue(any("invalid ISO date" in issue.message for issue in report.issues))
            self.assertTrue(any("habits_json must be an object with boolean values" in issue.message for issue in report.issues))
            self.assertTrue(any("people_json must be a list of strings" in issue.message for issue in report.issues))

    def test_day_marker_form_helpers(self):
        self.assertEqual(parse_people_text("Alice, Bob\nAlice\n"), ["Alice", "Bob"])
        self.assertEqual(format_people_text(["Alice", "Bob"]), "Alice\nBob")
        self.assertIsNone(parse_mood_value(""))
        self.assertEqual(parse_mood_value("7.5"), 7.5)

    def test_habit_values_include_month_habits_unchecked(self):
        self.assertEqual(
            habit_values_for_day(
                {"exercise", "meditate", "read"},
                {"exercise": True, "read": False},
            ),
            {
                "exercise": True,
                "meditate": False,
                "read": False,
            },
        )

    def test_month_habit_names_only_uses_selected_month(self):
        with self._repo() as repo:
            repo.upsert_day_marker(
                DayMarker(
                    day=date(2026, 7, 31),
                    habits={"july": True},
                    people=[],
                    quick_note_markdown="",
                    mood=None,
                )
            )
            repo.upsert_day_marker(
                DayMarker(
                    day=date(2026, 8, 1),
                    habits={"exercise": True},
                    people=[],
                    quick_note_markdown="",
                    mood=None,
                )
            )
            repo.upsert_day_marker(
                DayMarker(
                    day=date(2026, 8, 15),
                    habits={"meditate": False},
                    people=[],
                    quick_note_markdown="",
                    mood=None,
                )
            )
            repo.upsert_day_marker(
                DayMarker(
                    day=date(2026, 9, 1),
                    habits={"september": True},
                    people=[],
                    quick_note_markdown="",
                    mood=None,
                )
            )
            repo.commit()

            self.assertEqual(
                month_habit_names(repo, date(2026, 8, 20)),
                {"exercise", "meditate"},
            )

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

    def _repo(self):
        class RepoContext:
            def __enter__(self_inner):
                self_inner.directory = tempfile.TemporaryDirectory()
                self_inner.repo = SQLiteRepository(Path(self_inner.directory.name) / "timeline.db")
                self_inner.repo.ensure_schema()
                return self_inner.repo

            def __exit__(self_inner, exc_type, exc, tb):
                self_inner.repo.close()
                self_inner.directory.cleanup()

        return RepoContext()


if __name__ == "__main__":
    unittest.main()
