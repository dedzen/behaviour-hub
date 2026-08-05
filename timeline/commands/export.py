from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from timeline.api.query import Query
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource
from timeline.export.daily_note import (
    DailyMarkdownOptions,
    render_timeline_daily_note_markdown,
)
from timeline.export.to_markdown import MarkdownRenderOptions
from timeline.storage.repository import SQLiteRepository

app = typer.Typer(help="Export timeline data")


@app.command("markdown")
def export_markdown(
    day: Annotated[
        str,
        typer.Argument(help="Day to export, formatted as YYYY-MM-DD."),
    ],
    database: Annotated[
        Path,
        typer.Option("--database", help="SQLite database path."),
    ] = Path("timeline.db"),
    activity: Annotated[
        list[str] | None,
        typer.Option(
            "--activity",
            "-a",
            help="Important activity to include. Repeat for multiple activities.",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write markdown to this file instead of stdout."),
    ] = None,
    template: Annotated[
        Path | None,
        typer.Option("--template", help="Markdown template path."),
    ] = None,
    top_activity_exclusion: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-top-activity",
            help="Activity name to exclude from top activity and default important activities.",
        ),
    ] = None,
    default_activities: Annotated[
        int,
        typer.Option(
            "--default-activities",
            min=0,
            help="Number of top activities to use when no --activity is provided.",
        ),
    ] = 5,
) -> None:
    """Render the daily markdown note for a selected day."""

    try:
        selected_day = date.fromisoformat(day)
    except ValueError as error:
        raise typer.BadParameter("day must be formatted as YYYY-MM-DD") from error

    exclusions = top_activity_exclusion or ["sleep"]

    with SQLiteRepository(database) as repo:
        timeline = Timeline(repo)
        important_activities = _selected_activities(
            timeline,
            selected_day,
            activity or [],
            limit=default_activities,
        )
        markdown_options = None
        if template is not None:
            markdown_options = MarkdownRenderOptions(template_path=template)

        markdown = render_timeline_daily_note_markdown(
            timeline,
            selected_day,
            important_activities,
            top_activity_exclusion=exclusions,
            options=DailyMarkdownOptions(markdown_options=markdown_options),
        )

    if output is None:
        typer.echo(markdown, nl=False)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    typer.echo(f"Wrote {output}")


def _selected_activities(
    timeline: Timeline,
    day: date,
    requested: list[str],
    *,
    limit: int,
) -> list[str]:
    explicit = _unique_requested(requested)
    if explicit or limit <= 0:
        return explicit

    df = (
        Timeline(timeline.repo, Query())
        .day(day)
        .source(DeviceSource.EMBED)
        .to_clipped_polars()
    )

    if df.is_empty():
        return []

    top = (
        df
        .group_by("name")
        .agg(pl.sum("duration_seconds").alias("total_seconds"))
        .sort(["total_seconds", "name"], descending=[True, False])
        .head(limit)
    )

    return [row["name"] for row in top.to_dicts()]


def _unique_requested(activities: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for activity in activities:
        activity = activity.strip()
        if not activity or activity in seen:
            continue
        seen.add(activity)
        result.append(activity)
    return result
