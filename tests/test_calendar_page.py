from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from nice_ui.pages.calendar import (
    CalendarDayMetrics,
    CalendarGoalShade,
    calendar_day_metrics,
    calendar_day_summary,
    calendar_goal_shade,
    calendar_shortcut_script,
    format_calendar_duration,
    marker_indicator_text,
    month_grid_dates,
    month_start,
    shift_month,
)
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Chunk, DayMarker, Event
from timeline.goals.models import (
    ActivityDurationRule,
    GoalOperator,
    GoalPeriod,
    GoalSchedule,
)
from timeline.goals.repository import GoalRepository
from timeline.goals.service import GoalService
from timeline.storage.repository import SQLiteRepository


class CalendarPageHelpersTest(unittest.TestCase):
    def test_goal_shades_cover_open_and_completed_days(self):
        self.assertEqual(
            calendar_goal_shade(total=0, met=0, day_ended=True),
            CalendarGoalShade.NONE,
        )
        self.assertEqual(
            calendar_goal_shade(total=2, met=0, day_ended=False),
            CalendarGoalShade.OPEN,
        )
        self.assertEqual(
            calendar_goal_shade(total=2, met=0, day_ended=True),
            CalendarGoalShade.NONE_MET,
        )
        self.assertEqual(
            calendar_goal_shade(total=2, met=1, day_ended=True),
            CalendarGoalShade.SOME_MET,
        )
        self.assertEqual(
            calendar_goal_shade(total=2, met=2, day_ended=True),
            CalendarGoalShade.ALL_MET,
        )

    def test_calendar_metrics_evaluate_daily_goals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline_repo = SQLiteRepository(root / "timeline.db")
            timeline_repo.ensure_schema()
            goals = GoalService(root / "goals.db")
            goals.initialize()
            goals_to_create = (
                ("Short focus", 3600),
                ("Long focus", 3 * 3600),
            )
            for title, target_seconds in goals_to_create:
                goals.create_goal(
                    schedule=GoalSchedule.ONE_OFF,
                    period=GoalPeriod.DAY,
                    selected_start=date(2026, 8, 1),
                    selected_end=None,
                    title=title,
                    rule=ActivityDurationRule(
                        source=DeviceSource.EMBED,
                        category="Work",
                        activity="Working",
                        operator=GoalOperator.AT_LEAST,
                        target_seconds=target_seconds,
                    ),
                )
            self._insert_chunk(
                timeline_repo,
                datetime(2026, 8, 1, 9),
                datetime(2026, 8, 1, 11),
                DeviceSource.EMBED,
                "Work",
                "Working",
            )
            timeline_repo.commit()

            with GoalRepository(root / "goals.db") as goal_repo:
                metric = calendar_day_metrics(
                    Timeline(timeline_repo),
                    date(2026, 8, 1),
                    goal_repo=goal_repo,
                    now=datetime(2026, 8, 2),
                )

            timeline_repo.close()
            self.assertEqual(metric.goals_met, 1)
            self.assertEqual(metric.goals_total, 2)
            self.assertEqual(metric.goal_shade, CalendarGoalShade.SOME_MET)

    def test_month_grid_includes_leading_and_trailing_days(self):
        weeks = month_grid_dates(2026, 8)

        self.assertEqual(weeks[0][0], date(2026, 7, 27))
        self.assertEqual(weeks[0][-1], date(2026, 8, 2))
        self.assertEqual(weeks[-1][0], date(2026, 8, 31))
        self.assertEqual(weeks[-1][-1], date(2026, 9, 6))

    def test_month_helpers_keep_first_of_month(self):
        self.assertEqual(month_start(date(2026, 8, 17)), date(2026, 8, 1))
        self.assertEqual(shift_month(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(shift_month(date(2026, 1, 1), -1), date(2025, 12, 1))

    def test_calendar_day_summary_collects_picture_and_marker_indicators(self):
        with self._repo() as repo:
            repo.upsert_day_marker(
                DayMarker(
                    day=date(2026, 8, 1),
                    habits={"exercise": True, "alcohol": False},
                    people=["Alice", "Bob"],
                    quick_note_markdown="note",
                    mood=7,
                )
            )
            self._insert_chunk(
                repo,
                datetime(2026, 8, 1, 9),
                datetime(2026, 8, 1, 11),
                DeviceSource.EMBED,
                "Work",
                "Working",
            )
            self._insert_chunk(
                repo,
                datetime(2026, 8, 1, 9, 30),
                datetime(2026, 8, 1, 10),
                DeviceSource.PHONE,
                "Screen",
                "Screen on",
            )
            repo.commit()

            summary = calendar_day_summary(
                Timeline(repo),
                date(2026, 8, 1),
                visible_month=date(2026, 8, 1),
                selected_day=date(2026, 8, 1),
                today=date(2026, 8, 2),
            )

            self.assertTrue(summary.in_month)
            self.assertTrue(summary.is_selected)
            self.assertFalse(summary.is_today)
            self.assertEqual(summary.tracked_time, "2:00")
            self.assertEqual(summary.screen_time, "0:30")
            self.assertEqual(summary.mood, 7)
            self.assertEqual(summary.people_count, 2)
            self.assertEqual(summary.habits_done, 1)
            self.assertEqual(summary.habits_total, 2)
            self.assertEqual(marker_indicator_text(summary), "2")

    def test_calendar_duration_uses_hours_and_zero_padded_minutes(self):
        self.assertEqual(format_calendar_duration(0), "0:00")
        self.assertEqual(format_calendar_duration(30), "0:00")
        self.assertEqual(format_calendar_duration(32 * 60), "0:32")
        self.assertEqual(format_calendar_duration(6 * 3600 + 32 * 60 + 45), "6:32")
        self.assertEqual(format_calendar_duration(12 * 3600 + 3 * 60), "12:03")

    def test_cached_metrics_can_be_restamped_for_selection_state(self):
        metric = CalendarDayMetrics(
            day=date(2026, 8, 2),
            tracked_time="1:00",
            screen_time="0:10",
            mood=None,
            has_note=False,
            people_count=0,
            habits_done=0,
            habits_total=0,
        )

        selected = metric.with_state(
            visible_month=date(2026, 8, 1),
            selected_day=date(2026, 8, 2),
            today=date(2026, 8, 3),
        )
        unselected = metric.with_state(
            visible_month=date(2026, 8, 1),
            selected_day=date(2026, 8, 4),
            today=date(2026, 8, 3),
        )

        self.assertTrue(selected.is_selected)
        self.assertFalse(unselected.is_selected)
        self.assertEqual(selected.tracked_time, unselected.tracked_time)

    def test_calendar_shortcut_script_ignores_text_fields_and_codemirror(self):
        script = calendar_shortcut_script()

        self.assertIn('"key": "c"', script)
        self.assertIn('"code": "KeyC"', script)
        self.assertIn('"key": "s"', script)
        self.assertIn('"code": "KeyS"', script)
        self.assertIn('"key": "ArrowLeft"', script)
        self.assertIn('"code": "ArrowLeft"', script)
        self.assertIn('"key": "ArrowRight"', script)
        self.assertIn('"code": "ArrowRight"', script)
        self.assertIn('"ctrl": true', script)
        self.assertIn('"ignoreEditable": false', script)
        self.assertIn("textarea", script)
        self.assertIn(".cm-editor", script)
        self.assertIn(".calendar-fold-toggle", script)
        self.assertIn(".day-marker-save-action", script)
        self.assertIn(".calendar-prev-day-action", script)
        self.assertIn(".calendar-next-day-action", script)

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
