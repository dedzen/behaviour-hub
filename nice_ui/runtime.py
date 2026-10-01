from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import logging
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from nicegui import run
from nicegui.client import Client

from timeline.api.timeline import Timeline
from timeline.application.mutations import ImportPreview, MutationResult, TimelineMutationService
from timeline.domain.models import DayMarker, Event
from timeline.goals.models import (
    ActivityDurationRule,
    GoalDefinition,
    GoalPeriod,
    GoalSchedule,
    GoalSeries,
)
from timeline.goals.repository import GoalRepository
from timeline.goals.service import GoalService
from timeline.storage.repository import SQLiteRepository


logger = logging.getLogger(__name__)
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class DataChange:
    events_changed: bool = False
    marker_days: frozenset[date] = frozenset()
    goals_changed: bool = False


class ChangeBus:
    def __init__(self):
        self._subscribers: dict[str, tuple[Client, Callable[[DataChange], None]]] = {}

    def subscribe(self, client: Client, callback: Callable[[DataChange], None]) -> str:
        token = uuid4().hex
        self._subscribers[token] = (client, callback)
        return token

    def unsubscribe(self, token: str) -> None:
        self._subscribers.pop(token, None)

    def publish(self, change: DataChange) -> None:
        for token, (client, callback) in list(self._subscribers.items()):
            if client.is_deleted:
                self.unsubscribe(token)
                continue
            try:
                with client:
                    callback(change)
            except Exception:
                logger.exception("Failed to refresh dashboard subscriber %s", token)


class DashboardRuntime:
    """Process-wide coordination without process-wide UI or DB connections."""

    def __init__(self, database: Path, goals_database: Path | None = None):
        self.database = database
        self.goals_database = goals_database or database.with_name("goals.db")
        self.service = TimelineMutationService(database)
        self.goal_service = GoalService(self.goals_database)
        self.changes = ChangeBus()
        self._write_lock = asyncio.Lock()

    def initialize(self) -> None:
        self.service.initialize()
        self.goal_service.initialize()

    async def run_io(self, operation: Callable[[], R]) -> R | None:
        """Serialize shared file/device operations with database mutations."""
        async with self._write_lock:
            return await run.io_bound(operation)

    async def _execute(
        self,
        operation: Callable[[], MutationResult],
        change: DataChange,
    ) -> MutationResult:
        result = await self.run_io(operation)
        if result is None:
            raise RuntimeError("Operation was cancelled during application shutdown")
        self.changes.publish(change)
        return result

    async def update_event(self, event: Event, expected_revision: int) -> MutationResult:
        return await self._execute(
            lambda: self.service.update_event(event, expected_revision),
            DataChange(events_changed=True),
        )

    async def delete_event(self, event_id: int, expected_revision: int) -> MutationResult:
        return await self._execute(
            lambda: self.service.delete_event(event_id, expected_revision),
            DataChange(events_changed=True),
        )

    async def delete_events(self, event_revisions: dict[int, int]) -> MutationResult:
        return await self._execute(
            lambda: self.service.delete_events(event_revisions),
            DataChange(events_changed=True),
        )

    async def save_day_marker(
        self,
        marker: DayMarker,
        expected_revision: int,
    ) -> MutationResult:
        return await self._execute(
            lambda: self.service.save_day_marker(marker, expected_revision),
            DataChange(marker_days=frozenset({marker.day})),
        )

    async def rebuild_chunks(self) -> MutationResult:
        return await self._execute(
            self.service.rebuild_chunks,
            DataChange(events_changed=True),
        )

    async def import_embed(self, filename: Path) -> MutationResult:
        return await self._execute(
            lambda: self.service.import_embed(filename),
            DataChange(events_changed=True),
        )

    async def preview_embed(self, filename: Path) -> ImportPreview:
        result = await self.run_io(lambda: self.service.preview_embed(filename))
        if result is None:
            raise RuntimeError("Operation was cancelled during application shutdown")
        return result

    async def import_android(self, filename: Path, strategy: str) -> MutationResult:
        return await self._execute(
            lambda: self.service.import_android(filename, strategy),
            DataChange(events_changed=True),
        )

    async def preview_android(self, filename: Path, strategy: str) -> ImportPreview:
        result = await self.run_io(lambda: self.service.preview_android(filename, strategy))
        if result is None:
            raise RuntimeError("Operation was cancelled during application shutdown")
        return result

    async def _execute_goal(self, operation: Callable[[], R]) -> R:
        result = await self.run_io(operation)
        if result is None:
            raise RuntimeError("Operation was cancelled during application shutdown")
        self.changes.publish(DataChange(goals_changed=True))
        return result

    async def create_goal(
        self,
        *,
        schedule: GoalSchedule,
        period: GoalPeriod,
        selected_start: date,
        selected_end: date | None,
        title: str,
        rule: ActivityDurationRule,
    ) -> GoalDefinition:
        return await self._execute_goal(lambda: self.goal_service.create_goal(
            schedule=schedule,
            period=period,
            selected_start=selected_start,
            selected_end=selected_end,
            title=title,
            rule=rule,
        ))

    async def revise_goal(
        self,
        series_id: int,
        expected_revision: int,
        *,
        effective_from: date,
        title: str,
        rule: ActivityDurationRule,
    ) -> GoalDefinition:
        return await self._execute_goal(lambda: self.goal_service.revise_goal(
            series_id,
            expected_revision,
            effective_from=effective_from,
            title=title,
            rule=rule,
        ))

    async def archive_goal(self, series_id: int, expected_revision: int) -> GoalSeries:
        return await self._execute_goal(
            lambda: self.goal_service.archive_goal(series_id, expected_revision)
        )

    async def delete_goal(self, series_id: int, expected_revision: int) -> bool:
        def delete() -> bool:
            self.goal_service.delete_goal(series_id, expected_revision)
            return True
        return await self._execute_goal(delete)

    async def duplicate_goal(self, series_id: int, selected_period: date) -> GoalDefinition:
        return await self._execute_goal(
            lambda: self.goal_service.duplicate_one_off(
                series_id, selected_period=selected_period
            )
        )


class DashboardSession:
    def __init__(self, runtime: DashboardRuntime, client: Client):
        self.runtime = runtime
        self.client = client
        self.repo = SQLiteRepository(runtime.database)
        self.repo.ensure_schema()
        self.goal_repo = GoalRepository(runtime.goals_database)
        self.goal_repo.ensure_schema()
        self.timeline = Timeline(self.repo)
        self._subscription_tokens: list[str] = []
        self._closed = False
        client.on_delete(self.close)

    def subscribe(self, callback: Callable[[DataChange], None]) -> None:
        self._subscription_tokens.append(
            self.runtime.changes.subscribe(self.client, callback)
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for token in self._subscription_tokens:
            self.runtime.changes.unsubscribe(token)
        self._subscription_tokens.clear()
        self.repo.close()
        self.goal_repo.close()
