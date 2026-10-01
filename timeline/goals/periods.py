from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from timeline.goals.models import GoalPeriod


@dataclass(frozen=True, slots=True)
class PeriodWindow:
    kind: GoalPeriod
    start: date
    end_exclusive: date

    @property
    def start_datetime(self) -> datetime:
        return datetime.combine(self.start, time.min)

    @property
    def end_datetime(self) -> datetime:
        return datetime.combine(self.end_exclusive, time.min)


def period_start(kind: GoalPeriod, selected: date) -> date:
    if kind == GoalPeriod.DAY:
        return selected
    return selected - timedelta(days=selected.weekday())


def next_period_start(kind: GoalPeriod, start: date) -> date:
    return start + timedelta(days=1 if kind == GoalPeriod.DAY else 7)


def previous_period_start(kind: GoalPeriod, start: date) -> date:
    return start - timedelta(days=1 if kind == GoalPeriod.DAY else 7)


def period_window(kind: GoalPeriod, selected: date) -> PeriodWindow:
    start = period_start(kind, selected)
    return PeriodWindow(kind, start, next_period_start(kind, start))


def period_is_closed(window: PeriodWindow, now: datetime | None = None) -> bool:
    return (now or datetime.now()) >= window.end_datetime


def period_is_future(window: PeriodWindow, now: datetime | None = None) -> bool:
    return (now or datetime.now()) < window.start_datetime
