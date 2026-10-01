from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.interval_builder import IntervalBuilder
from timeline.domain.models import Event
from timeline.goals.evaluator import DEFAULT_EVALUATORS
from timeline.goals.models import (
    ActivityDurationRule,
    GoalOperator,
    GoalPeriod,
    GoalSchedule,
    GoalStatus,
    ProgressStatus,
)
from timeline.goals.periods import period_window
from timeline.goals.repository import GoalRepository
from timeline.goals.service import GoalService
from timeline.storage.errors import ConcurrentModificationError
from timeline.storage.repository import SQLiteRepository

from nicegui.client import Client
from nicegui.page import page
from nice_ui.pages.goals import GoalsPage
from nice_ui.runtime import DashboardRuntime, DashboardSession
from uuid import uuid4


def focus_rule(target: int = 3600, operator: GoalOperator = GoalOperator.AT_LEAST):
    return ActivityDurationRule(
        DeviceSource.EMBED, "Work", "Focus", operator, target
    )


class GoalPersistenceTest(unittest.TestCase):
    def test_goal_data_is_created_in_a_separate_database(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = GoalService(root / "goals.db")
            service.initialize()
            definition = service.create_goal(
                schedule=GoalSchedule.ONE_OFF,
                period=GoalPeriod.DAY,
                selected_start=date(2026, 8, 1),
                selected_end=None,
                title="Focus today",
                rule=focus_rule(),
            )

            self.assertTrue((root / "goals.db").exists())
            self.assertFalse((root / "timeline.db").exists())
            self.assertEqual(definition.series.end_period_exclusive, date(2026, 8, 2))

    def test_effective_versions_preserve_completed_periods(self):
        with TemporaryDirectory() as directory:
            service = GoalService(Path(directory) / "goals.db")
            service.initialize()
            original = service.create_goal(
                schedule=GoalSchedule.RECURRING,
                period=GoalPeriod.DAY,
                selected_start=date(2026, 8, 1),
                selected_end=None,
                title="One hour",
                rule=focus_rule(3600),
            )
            revised = service.revise_goal(
                original.series.id,
                original.series.revision,
                effective_from=date(2026, 8, 3),
                title="Two hours",
                rule=focus_rule(7200),
                today=date(2026, 8, 3),
            )

            with GoalRepository(service.database) as repo:
                before = repo.definition(original.series.id, date(2026, 8, 2))
                after = repo.definition(original.series.id, date(2026, 8, 3))
                self.assertEqual(len(repo.list_versions(original.series.id)), 2)
            self.assertEqual(before.rule.target_seconds, 3600)  # type: ignore[union-attr]
            self.assertEqual(after.rule.target_seconds, 7200)  # type: ignore[union-attr]
            self.assertEqual(revised.series.revision, 2)

    def test_completed_period_revisions_and_stale_writes_are_rejected(self):
        with TemporaryDirectory() as directory:
            service = GoalService(Path(directory) / "goals.db")
            service.initialize()
            goal = service.create_goal(
                schedule=GoalSchedule.RECURRING,
                period=GoalPeriod.DAY,
                selected_start=date(2026, 8, 1),
                selected_end=None,
                title="Focus",
                rule=focus_rule(),
            )
            with self.assertRaisesRegex(ValueError, "Completed"):
                service.revise_goal(
                    goal.series.id,
                    goal.series.revision,
                    effective_from=date(2026, 8, 1),
                    title="Past",
                    rule=focus_rule(),
                    today=date(2026, 8, 2),
                )
            service.archive_goal(
                goal.series.id, goal.series.revision, today=date(2026, 8, 1)
            )
            with self.assertRaises(ConcurrentModificationError):
                service.delete_goal(goal.series.id, goal.series.revision)

    def test_archiving_preserves_current_period_and_stops_next(self):
        with TemporaryDirectory() as directory:
            service = GoalService(Path(directory) / "goals.db")
            service.initialize()
            goal = service.create_goal(
                schedule=GoalSchedule.RECURRING,
                period=GoalPeriod.WEEK,
                selected_start=date(2026, 8, 3),
                selected_end=None,
                title="Weekly focus",
                rule=focus_rule(),
            )
            archived = service.archive_goal(
                goal.series.id, goal.series.revision, today=date(2026, 8, 5)
            )
            with GoalRepository(service.database) as repo:
                current = repo.definitions_for_period(GoalPeriod.WEEK, date(2026, 8, 3))
                following = repo.definitions_for_period(GoalPeriod.WEEK, date(2026, 8, 10))
            self.assertEqual(archived.status, GoalStatus.ARCHIVED)
            self.assertEqual(len(current), 1)
            self.assertEqual(following, [])


class GoalEvaluationTest(unittest.TestCase):
    def test_activity_duration_uses_exact_source_category_activity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            timeline_repo = SQLiteRepository(root / "timeline.db")
            timeline_repo.ensure_schema()
            events = [
                Event(datetime(2026, 8, 1, 9), DeviceSource.EMBED, EventKind.INTERVAL_START, "Work", "Focus"),
                Event(datetime(2026, 8, 1, 10), DeviceSource.EMBED, EventKind.INTERVAL_END, "Work", "Focus"),
                Event(datetime(2026, 8, 1, 9), DeviceSource.PHONE, EventKind.INTERVAL_START, "Work", "Focus"),
                Event(datetime(2026, 8, 1, 11), DeviceSource.PHONE, EventKind.INTERVAL_END, "Work", "Focus"),
            ]
            for event in events:
                timeline_repo.insert_event(event)
            chunks, _ = IntervalBuilder.build(events)
            timeline_repo.replace_chunks(chunks)
            timeline_repo.conn.commit()

            goal_service = GoalService(root / "goals.db")
            goal_service.initialize()
            definition = goal_service.create_goal(
                schedule=GoalSchedule.ONE_OFF,
                period=GoalPeriod.DAY,
                selected_start=date(2026, 8, 1),
                selected_end=None,
                title="Focus",
                rule=focus_rule(3600),
            )
            progress = DEFAULT_EVALUATORS.evaluate(
                definition,
                Timeline(timeline_repo),
                period_window(GoalPeriod.DAY, date(2026, 8, 1)),
                now=datetime(2026, 8, 1, 12),
            )
            self.assertEqual(progress.actual_seconds, 3600)
            self.assertEqual(progress.status, ProgressStatus.MET)
            timeline_repo.close()

    def test_at_most_remains_on_track_until_close_and_then_is_met(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            repo = SQLiteRepository(root / "timeline.db")
            repo.ensure_schema()
            goal_service = GoalService(root / "goals.db")
            goal_service.initialize()
            definition = goal_service.create_goal(
                schedule=GoalSchedule.ONE_OFF,
                period=GoalPeriod.DAY,
                selected_start=date(2026, 8, 1),
                selected_end=None,
                title="Limit",
                rule=focus_rule(3600, GoalOperator.AT_MOST),
            )
            window = period_window(GoalPeriod.DAY, date(2026, 8, 1))
            active = DEFAULT_EVALUATORS.evaluate(
                definition, Timeline(repo), window, now=datetime(2026, 8, 1, 12)
            )
            closed = DEFAULT_EVALUATORS.evaluate(
                definition, Timeline(repo), window, now=datetime(2026, 8, 2)
            )
            self.assertEqual(active.status, ProgressStatus.ON_TRACK)
            self.assertEqual(closed.status, ProgressStatus.MET)
            repo.close()


class GoalsPageTest(unittest.TestCase):
    def test_page_constructs_with_separate_session_repository(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = DashboardRuntime(root / "timeline.db", root / "goals.db")
            runtime.initialize()
            client = Client(page(f"/goals-test-{uuid4().hex}"))
            with client:
                session = DashboardSession(runtime, client)
                goals = GoalsPage(session.timeline, session.goal_repo, runtime)
            self.assertEqual(goals.period, GoalPeriod.DAY)
            self.assertIsNot(session.goal_repo, runtime.goal_service)
            client.delete()


class GoalRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_committed_goal_change_is_published(self):
        class FakeClient:
            is_deleted = False

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = DashboardRuntime(root / "timeline.db", root / "goals.db")
            runtime.initialize()
            changes = []
            runtime.changes.subscribe(FakeClient(), changes.append)  # type: ignore[arg-type]

            async def immediately(callback):
                return callback()

            with patch("nice_ui.runtime.run.io_bound", side_effect=immediately):
                await runtime.create_goal(
                    schedule=GoalSchedule.RECURRING,
                    period=GoalPeriod.DAY,
                    selected_start=date(2026, 8, 1),
                    selected_end=None,
                    title="Focus",
                    rule=focus_rule(),
                )

            self.assertEqual(len(changes), 1)
            self.assertTrue(changes[0].goals_changed)


if __name__ == "__main__":
    unittest.main()
