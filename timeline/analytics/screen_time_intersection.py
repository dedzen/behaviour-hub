from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

import polars as pl

from timeline.analytics.chunk_analytics import Period
from timeline.api.query import Query
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource


SCREEN_CATEGORY = "Screen"
SCREEN_ACTIVITY = "Screen on"


@dataclass(frozen=True, slots=True)
class _Interval:
    start: datetime
    end: datetime
    category: str | None
    name: str | None

    @property
    def seconds(self) -> int:
        return int((self.end - self.start).total_seconds())


def active_screen_intersection(
    timeline: Timeline,
    activities: Iterable[str],
    *,
    activity_source: DeviceSource = DeviceSource.EMBED,
    screen_source: DeviceSource = DeviceSource.PHONE,
    screen_category: str = SCREEN_CATEGORY,
    screen_activity: str = SCREEN_ACTIVITY,
) -> pl.DataFrame:
    """Calculate phone active-screen overlap with selected activity chunks."""

    selected_activities = frozenset(activity for activity in activities if activity)
    if not selected_activities:
        return _empty_result()

    activity_timeline = _scoped_timeline(
        timeline,
        sources=frozenset({activity_source}),
        activities=selected_activities,
    )
    screen_timeline = _scoped_timeline(
        timeline,
        sources=frozenset({screen_source}),
        categories=frozenset({screen_category}),
        activities=frozenset({screen_activity}),
    )

    activity_intervals = _intervals_from_frame(activity_timeline.to_clipped_polars())
    screen_intervals = _intervals_from_frame(screen_timeline.to_clipped_polars())

    return screen_intersection_summary(activity_intervals, screen_intervals)


def active_screen_intersection_over_time(
    timeline: Timeline,
    activities: Iterable[str],
    period: Period = "day",
    *,
    activity_source: DeviceSource = DeviceSource.EMBED,
    screen_source: DeviceSource = DeviceSource.PHONE,
    screen_category: str = SCREEN_CATEGORY,
    screen_activity: str = SCREEN_ACTIVITY,
) -> pl.DataFrame:
    """Calculate active-screen share for selected activities over time."""

    selected_activities = frozenset(activity for activity in activities if activity)
    if not selected_activities:
        return _empty_period_result()

    activity_timeline = _scoped_timeline(
        timeline,
        sources=frozenset({activity_source}),
        activities=selected_activities,
    )
    screen_timeline = _scoped_timeline(
        timeline,
        sources=frozenset({screen_source}),
        categories=frozenset({screen_category}),
        activities=frozenset({screen_activity}),
    )

    activity_period_intervals = _split_intervals_by_period(
        _intervals_from_frame(activity_timeline.to_clipped_polars()),
        period,
    )
    screen_period_intervals = _split_intervals_by_period(
        _intervals_from_frame(screen_timeline.to_clipped_polars()),
        period,
    )

    periods = sorted(
        {period_start for period_start, _ in activity_period_intervals}
        | {period_start for period_start, _ in screen_period_intervals}
    )
    rows: list[dict[str, object]] = []

    for period_start in periods:
        activity_period = [
            interval
            for interval_period, interval in activity_period_intervals
            if interval_period == period_start
        ]
        if not activity_period:
            continue

        screen_period = [
            interval
            for interval_period, interval in screen_period_intervals
            if interval_period == period_start
        ]
        summary = screen_intersection_summary(activity_period, screen_period)
        rows.extend(
            {
                "period": period_start,
                **row,
            }
            for row in summary.to_dicts()
        )

    if not rows:
        return _empty_period_result()

    return pl.DataFrame(rows, schema=_period_result_schema()).sort(
        ["period", "name", "category"]
    )


def screen_intersection_summary(
    activity_intervals: list[_Interval],
    screen_intervals: list[_Interval],
) -> pl.DataFrame:
    activity_totals: dict[tuple[str | None, str | None], int] = {}
    overlap_totals: dict[tuple[str | None, str | None], int] = {}

    for interval in activity_intervals:
        key = (interval.category, interval.name)
        activity_totals[key] = activity_totals.get(key, 0) + interval.seconds

    activity_intervals = sorted(activity_intervals, key=lambda interval: (interval.start, interval.end))
    screen_intervals = sorted(screen_intervals, key=lambda interval: (interval.start, interval.end))

    screen_total_seconds = sum(interval.seconds for interval in screen_intervals)
    i = 0
    j = 0
    while i < len(activity_intervals) and j < len(screen_intervals):
        activity = activity_intervals[i]
        screen = screen_intervals[j]
        start = max(activity.start, screen.start)
        end = min(activity.end, screen.end)

        if start < end:
            key = (activity.category, activity.name)
            overlap_totals[key] = overlap_totals.get(key, 0) + int((end - start).total_seconds())

        if activity.end <= screen.end:
            i += 1
        else:
            j += 1

    rows = []
    for category, name in sorted(activity_totals, key=lambda key: ((key[0] or ""), (key[1] or ""))):
        activity_seconds = activity_totals[(category, name)]
        overlap_seconds = overlap_totals.get((category, name), 0)
        rows.append(
            {
                "category": category,
                "name": name,
                "activity_seconds": activity_seconds,
                "screen_seconds": overlap_seconds,
                "activity_without_screen_seconds": activity_seconds - overlap_seconds,
                "screen_total_seconds": screen_total_seconds,
                "activity_screen_percent": (
                    overlap_seconds / activity_seconds * 100
                    if activity_seconds
                    else 0.0
                ),
            }
        )

    if not rows:
        return _empty_result()

    return pl.DataFrame(rows, schema=_result_schema()).sort(
        "screen_seconds",
        descending=True,
    )


def _scoped_timeline(
    timeline: Timeline,
    *,
    sources: frozenset[DeviceSource],
    categories: frozenset[str] = frozenset(),
    activities: frozenset[str] = frozenset(),
) -> Timeline:
    query = Query(
        start=timeline.query.start,
        end=timeline.query.end,
        categories=categories,
        activities=activities,
        sources=sources,
        weekday=timeline.query.weekday,
    )
    return Timeline(timeline.repo, query)


def _intervals_from_frame(df: pl.DataFrame) -> list[_Interval]:
    return [
        _Interval(
            start=row["start_timestamp"],
            end=row["end_timestamp"],
            category=row["category"],
            name=row["name"],
        )
        for row in df.select(
            "start_timestamp",
            "end_timestamp",
            "category",
            "name",
        ).to_dicts()
    ]


def _split_intervals_by_period(
    intervals: list[_Interval],
    period: Period,
) -> list[tuple[datetime, _Interval]]:
    rows = []

    for interval in intervals:
        start = interval.start
        while start < interval.end:
            period_start = _period_start(start, period)
            period_end = _next_period_start(start, period)
            segment_end = min(interval.end, period_end)
            rows.append((
                period_start,
                _Interval(
                    start=start,
                    end=segment_end,
                    category=interval.category,
                    name=interval.name,
                ),
            ))
            start = segment_end

    return rows


def _next_period_start(value: datetime, period: Period) -> datetime:
    current = _period_start(value, period)

    match period:
        case "hour":
            return current + timedelta(hours=1)
        case "day":
            return current + timedelta(days=1)
        case "week":
            return current + timedelta(days=7)
        case "month":
            if current.month == 12:
                return current.replace(year=current.year + 1, month=1)
            return current.replace(month=current.month + 1)
        case "year":
            return current.replace(year=current.year + 1)


def _period_start(value: datetime, period: Period) -> datetime:
    match period:
        case "hour":
            return value.replace(minute=0, second=0, microsecond=0)
        case "day":
            return value.replace(hour=0, minute=0, second=0, microsecond=0)
        case "week":
            day_start = value.replace(hour=0, minute=0, second=0, microsecond=0)
            return day_start - timedelta(days=day_start.weekday())
        case "month":
            return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        case "year":
            return value.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


def _period_result_schema() -> dict[str, pl.DataType]:
    return {
        "period": pl.Datetime,
        **_result_schema(),
    }


def _result_schema() -> dict[str, pl.DataType]:
    return {
        "category": pl.Utf8,
        "name": pl.Utf8,
        "activity_seconds": pl.Int64,
        "screen_seconds": pl.Int64,
        "activity_without_screen_seconds": pl.Int64,
        "screen_total_seconds": pl.Int64,
        "activity_screen_percent": pl.Float64,
    }


def _empty_result() -> pl.DataFrame:
    return pl.DataFrame(schema=_result_schema())


def _empty_period_result() -> pl.DataFrame:
    return pl.DataFrame(schema=_period_result_schema())
