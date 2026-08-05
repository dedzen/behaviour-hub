from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import polars as pl

from timeline.analytics.screen_time_intersection import (
    active_screen_intersection,
)
from timeline.api.query import Query
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource
from timeline.export.to_markdown import DailyNoteData, MarkdownRenderOptions, render_daily_note_markdown
from timeline.statistics.tools import human_duration
from timeline.validation.report import Severity, ValidationReport
from timeline.validation.validator import Validator


@dataclass(frozen=True, slots=True)
class DailyMarkdownOptions:
    activity_source: DeviceSource = DeviceSource.EMBED
    screen_source: DeviceSource = DeviceSource.PHONE
    screen_category: str = "Screen"
    screen_activity: str = "Screen on"
    markdown_options: MarkdownRenderOptions | None = None
    template: str | None = None


def render_timeline_daily_note_markdown(
    timeline: Timeline,
    day: date | str,
    important_activities: Iterable[str],
    *,
    top_activity_exclusion: str | Iterable[str] | None = "sleep",
    options: DailyMarkdownOptions | None = None,
    overrides: dict[str, Any] | None = None,
) -> str:
    """Build and render a daily note from a Timeline."""

    data = build_daily_note_data(
        timeline,
        day,
        important_activities,
        top_activity_exclusion=top_activity_exclusion,
        options=options,
    )

    options = options or DailyMarkdownOptions()
    return render_daily_note_markdown(
        data,
        options=options.markdown_options,
        template=options.template,
        overrides=overrides,
    )


def build_daily_note_data(
    timeline: Timeline,
    day: date | str,
    important_activities: Iterable[str],
    *,
    top_activity_exclusion: str | Iterable[str] | None = "sleep",
    options: DailyMarkdownOptions | None = None,
) -> DailyNoteData:
    options = options or DailyMarkdownOptions()
    selected_day = date.fromisoformat(day) if isinstance(day, str) else day
    selected_activities = _normalize_activities(important_activities)
    day_timeline = _unfiltered_day_timeline(timeline, selected_day)
    activity_timeline = day_timeline.source(options.activity_source)
    screen_timeline = (
        day_timeline
        .source(options.screen_source)
        .category(options.screen_category)
        .activity(options.screen_activity)
    )

    activity_df = activity_timeline.to_clipped_polars()
    screen_df = screen_timeline.to_clipped_polars()
    important_df = _important_activity_frame(activity_df, selected_activities)
    intersection_df = active_screen_intersection(
        day_timeline,
        selected_activities,
        activity_source=options.activity_source,
        screen_source=options.screen_source,
        screen_category=options.screen_category,
        screen_activity=options.screen_activity,
    )

    tracked_seconds = _sum_seconds(activity_df)
    active_screen_seconds = _sum_seconds(screen_df)
    sleep_seconds = _activity_seconds(activity_df, "Sleep")
    yesterday_df = _activity_time_comparison(
        timeline,
        selected_day,
        selected_activities,
        days_back=1,
        options=options,
    )
    week_df = _activity_time_comparison(
        timeline,
        selected_day,
        selected_activities,
        days_back=7,
        options=options,
    )

    return DailyNoteData(
        date=selected_day,
        tracked_time=human_duration(tracked_seconds),
        active_screen_time=human_duration(active_screen_seconds),
        top_activity=_top_activity(activity_df, top_activity_exclusion),
        important_activities=_activity_rows(
            important_df,
            daily_comparison=yesterday_df,
            weekly_comparison=week_df,
        ),
        screen_time_intersections=_intersection_rows(intersection_df),
        validation_status=_validation_status(Validator(timeline.repo).validate()),
        extras={
            "iso_date": selected_day.isoformat(),
            "iso_week": _iso_week(selected_day),
            "iso_tracked_text_time": _text_duration(tracked_seconds),
            "iso_screen_text_time": _text_duration(active_screen_seconds),
            "iso_sleep_time_text": _text_duration(sleep_seconds),
        },
    )


def _unfiltered_day_timeline(timeline: Timeline, day: date) -> Timeline:
    return Timeline(timeline.repo, Query()).day(day)


def _normalize_activities(activities: Iterable[str]) -> list[str]:
    return sorted({activity for activity in activities if activity})


def _important_activity_frame(df: pl.DataFrame, activities: list[str]) -> pl.DataFrame:
    if df.is_empty() or not activities:
        return df.head(0)

    return (
        df
        .filter(pl.col("name").is_in(activities))
        .group_by("name")
        .agg(
            pl.len().alias("sessions"),
            pl.sum("duration_seconds").alias("total_seconds"),
        )
        .sort("total_seconds", descending=True)
    )


def _activity_rows(
    df: pl.DataFrame,
    *,
    daily_comparison: pl.DataFrame,
    weekly_comparison: pl.DataFrame,
) -> list[str]:
    if df.is_empty():
        return []

    daily_changes = _change_by_activity(daily_comparison)
    weekly_changes = _change_by_activity(weekly_comparison)

    return [
        (
            f"{row['name']}({row['sessions']}) - "
            f"{human_duration(row['total_seconds'])} | "
            f"{daily_changes.get(row['name'], '+0.0%')} | "
            f"{weekly_changes.get(row['name'], '+0.0%')}"
        )
        for row in df.to_dicts()
    ]


def _intersection_rows(df: pl.DataFrame) -> list[str]:
    if df.is_empty():
        return []

    return [
        f"{row['name']}: {row['activity_screen_percent']:.1f}%"
        for row in df.to_dicts()
    ]


def _sum_seconds(df: pl.DataFrame) -> int:
    if df.is_empty():
        return 0
    return int(df.select(pl.sum("duration_seconds")).item() or 0)


def _activity_seconds(df: pl.DataFrame, activity: str) -> int:
    if df.is_empty():
        return 0

    value = (
        df
        .filter(pl.col("name").str.to_lowercase() == activity.lower())
        .select(pl.sum("duration_seconds"))
        .item()
    )
    return int(value or 0)


def _iso_week(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _text_duration(seconds: int) -> str:
    days, remainder = divmod(max(0, int(seconds)), 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(_plural(days, "day"))
    if hours:
        parts.append(_plural(hours, "hour"))
    if minutes:
        parts.append(_plural(minutes, "minute"))
    if seconds or not parts:
        parts.append(_plural(seconds, "second"))

    return " ".join(parts)


def _plural(value: int, unit: str) -> str:
    suffix = "" if value == 1 else "s"
    return f"{value} {unit}{suffix}"


def _validation_status(report: ValidationReport) -> str:
    errors = sum(1 for issue in report.issues if issue.severity == Severity.ERROR)
    warnings = sum(1 for issue in report.issues if issue.severity == Severity.WARNING)

    if errors:
        if warnings:
            return f"Invalid: {errors} errors, {warnings} warnings"
        return f"Invalid: {errors} errors"

    if warnings:
        return f"Valid: {warnings} warnings"

    return "Valid"


def _activity_time_comparison(
    timeline: Timeline,
    day: date,
    important_activities: list[str],
    *,
    days_back: int,
    options: DailyMarkdownOptions,
) -> pl.DataFrame:
    current = _activity_seconds_by_name(
        Timeline(timeline.repo, Query()).day(day).source(options.activity_source),
        important_activities,
        "today_seconds",
    )
    previous = _activity_seconds_over_days(
        timeline,
        day,
        important_activities,
        days_back=days_back,
        source=options.activity_source,
    )

    if current.is_empty():
        current = _zero_value_frame(
            important_activities,
            "today_seconds",
        )

    if current.is_empty() and previous.is_empty():
        return pl.DataFrame(schema={
            "name": pl.Utf8,
            "today_seconds": pl.Float64,
            "previous_seconds": pl.Float64,
        })

    return (
        current
        .join(previous, on="name", how="full", coalesce=True)
        .with_columns(
            pl.col("today_seconds").fill_null(0.0),
            pl.col("previous_seconds").fill_null(0.0),
        )
        .sort("name")
    )


def _activity_seconds_by_name(
    timeline: Timeline,
    activities: list[str],
    column_name: str,
) -> pl.DataFrame:
    df = timeline.activity(activities).to_clipped_polars() if activities else timeline.to_clipped_polars().head(0)
    if df.is_empty():
        return pl.DataFrame(schema={
            "name": pl.Utf8,
            column_name: pl.Float64,
        })

    return (
        df
        .group_by("name")
        .agg(pl.sum("duration_seconds").cast(pl.Float64).alias(column_name))
    )


def _activity_seconds_over_days(
    timeline: Timeline,
    day: date,
    activities: list[str],
    *,
    days_back: int,
    source: DeviceSource,
) -> pl.DataFrame:
    start = datetime.combine(day - timedelta(days=days_back), time.min)
    end = datetime.combine(day, time.min)
    df = (
        Timeline(timeline.repo, Query(start=start, end=end))
        .source(source)
        .activity(activities)
        .to_clipped_polars()
    )

    if df.is_empty():
        return pl.DataFrame(schema={
            "name": pl.Utf8,
            "previous_seconds": pl.Float64,
        })

    daily = (
        df
        .with_columns(pl.col("start_timestamp").dt.date().alias("day"))
        .group_by(["day", "name"])
        .agg(pl.sum("duration_seconds").alias("daily_seconds"))
    )

    return (
        daily
        .group_by("name")
        .agg(pl.mean("daily_seconds").cast(pl.Float64).alias("previous_seconds"))
    )


def _zero_value_frame(activities: list[str], column_name: str) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "name": activity,
                column_name: 0.0,
            }
            for activity in activities
        ],
        schema={
            "name": pl.Utf8,
            column_name: pl.Float64,
        },
    )


def _change_by_activity(df: pl.DataFrame) -> dict[str, str]:
    if df.is_empty():
        return {}

    return {
        row["name"]: _percentage_change(row["today_seconds"], row["previous_seconds"])
        for row in df.to_dicts()
    }


def _percentage_change(current: float, previous: float) -> str:
    if previous == 0:
        if current == 0:
            change = 0.0
        else:
            change = 100.0
    else:
        change = (current - previous) / previous * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


def _top_activity(
    df: pl.DataFrame,
    exclusions: str | Iterable[str] | None,
) -> str:
    if df.is_empty():
        return "Not available"

    excluded = _normalize_exclusions(exclusions)
    top = (
        df
        .filter(~pl.col("name").str.to_lowercase().is_in(excluded))
        .group_by(["category", "name"])
        .agg(pl.sum("duration_seconds").alias("total_seconds"))
        .sort("total_seconds", descending=True)
        .head(1)
    )

    if top.is_empty():
        return "Not available"

    row = top.to_dicts()[0]
    return f"{row['name']} ({human_duration(row['total_seconds'])})"


def _normalize_exclusions(exclusions: str | Iterable[str] | None) -> set[str]:
    if exclusions is None:
        return set()
    if isinstance(exclusions, str):
        return {exclusions.lower()}
    return {item.lower() for item in exclusions}
