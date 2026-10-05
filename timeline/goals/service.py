from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from timeline.api.timeline import Timeline
from timeline.goals.evaluator import DEFAULT_EVALUATORS
from timeline.goals.models import (
    ActivityDurationRule,
    GoalDefinition,
    GoalPeriod,
    GoalProgress,
    GoalSchedule,
    GoalSeries,
    GoalStatus,
)
from timeline.goals.periods import next_period_start, period_start, period_window
from timeline.goals.repository import GoalRepository


class GoalService:
    def __init__(self, database: Path):
        self.database = database

    def initialize(self) -> None:
        with GoalRepository(self.database) as repo:
            repo.ensure_schema()

    def create_goal(
        self,
        *,
        schedule: GoalSchedule,
        period: GoalPeriod,
        selected_start: date,
        selected_end: date | None,
        title: str,
        rule: ActivityDurationRule,
    ) -> GoalDefinition:
        start = period_start(period, selected_start)
        if schedule == GoalSchedule.ONE_OFF:
            end_exclusive = next_period_start(period, start)
        elif selected_end is not None:
            end_start = period_start(period, selected_end)
            if end_start < start:
                raise ValueError("Goal end must not be before its start")
            end_exclusive = next_period_start(period, end_start)
        else:
            end_exclusive = None
        with GoalRepository(self.database) as repo, repo.transaction(immediate=True):
            return repo.create(
                schedule=schedule,
                period=period,
                start_period=start,
                end_period_exclusive=end_exclusive,
                title=title,
                rule=rule,
            )

    def revise_goal(
        self,
        series_id: int,
        expected_revision: int,
        *,
        effective_from: date,
        title: str,
        rule: ActivityDurationRule,
        today: date | None = None,
    ) -> GoalDefinition:
        today = today or date.today()
        with GoalRepository(self.database) as repo, repo.transaction(immediate=True):
            series = repo.get_series(series_id)
            if series is None:
                raise ValueError("Goal not found")
            if series.status != GoalStatus.ACTIVE:
                raise ValueError("Archived goals cannot be revised")
            effective = period_start(series.period, effective_from)
            current = period_start(series.period, today)
            if effective < current:
                raise ValueError("Completed goal periods cannot be revised")
            if series.schedule == GoalSchedule.ONE_OFF:
                window = period_window(series.period, series.start_period)
                if today >= window.end_exclusive:
                    raise ValueError("Completed one-off goals are locked")
                effective = series.start_period
            if effective < series.start_period:
                raise ValueError("Revision cannot begin before the goal")
            if series.end_period_exclusive and effective >= series.end_period_exclusive:
                raise ValueError("Revision must begin before the goal ends")
            return repo.revise(
                series_id,
                expected_revision,
                effective_from=effective,
                title=title,
                rule=rule,
            )

    def archive_goal(
        self,
        series_id: int,
        expected_revision: int,
        *,
        today: date | None = None,
    ) -> GoalSeries:
        today = today or date.today()
        with GoalRepository(self.database) as repo, repo.transaction(immediate=True):
            series = repo.get_series(series_id)
            if series is None:
                raise ValueError("Goal not found")
            if series.status != GoalStatus.ACTIVE:
                raise ValueError("Goal is already archived")
            current = period_start(series.period, today)
            end = (
                series.start_period
                if current < series.start_period
                else next_period_start(series.period, current)
            )
            if series.end_period_exclusive is not None:
                end = min(end, series.end_period_exclusive)
            return repo.archive(
                series_id,
                expected_revision,
                end_period_exclusive=end,
            )

    def delete_goal(self, series_id: int, expected_revision: int) -> None:
        with GoalRepository(self.database) as repo, repo.transaction(immediate=True):
            repo.delete(series_id, expected_revision)

    def duplicate_one_off(
        self,
        series_id: int,
        *,
        selected_period: date,
    ) -> GoalDefinition:
        with GoalRepository(self.database) as repo:
            source_series = repo.get_series(series_id)
            if source_series is None:
                raise ValueError("Goal not found")
            versions = repo.list_versions(series_id)
            if not versions:
                raise ValueError("Goal has no definition")
            source = GoalDefinition(source_series, versions[-1])
        return self.create_goal(
            schedule=GoalSchedule.ONE_OFF,
            period=source_series.period,
            selected_start=selected_period,
            selected_end=None,
            title=source.version.title,
            rule=source.rule,
        )


def progress_for_period(
    repo: GoalRepository,
    timeline: Timeline,
    period: GoalPeriod,
    selected: date,
    *,
    now: datetime | None = None,
) -> list[GoalProgress]:
    window = period_window(period, selected)
    return [
        DEFAULT_EVALUATORS.evaluate(definition, timeline, window, now)
        for definition in repo.definitions_for_period(period, window.start)
    ]
