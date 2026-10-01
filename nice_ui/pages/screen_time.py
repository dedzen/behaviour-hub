from __future__ import annotations

import polars as pl
from nicegui import ui

from timeline.analytics.screen_time_intersection import (
    active_screen_intersection,
    active_screen_intersection_over_time,
)
from timeline.api.query import Query
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource
from timeline.statistics.tools import human_duration
from nice_ui.responsive import configure_responsive_table, responsive_chart_options


PERIODS = {
    "Day": "day",
    "Week": "week",
    "Month": "month",
    "Year": "year",
}


class ScreenTimeIntersectionView:
    def __init__(self):
        self.timeline: Timeline | None = None
        self.selected_activities: list[str] = []
        self.period = "Day"

        with ui.column().classes("w-full gap-4"):
            with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                self.activity_select = ui.select(
                    options=[],
                    value=[],
                    label="Activities",
                    multiple=True,
                    on_change=self._activities_changed,
                ).classes("min-w-0 basis-full sm:basis-auto flex-grow")
                self.clear_button = ui.button(
                    "Clear",
                    icon="clear",
                    on_click=self._clear,
                ).props("outline")
                ui.select(
                    list(PERIODS),
                    value=self.period,
                    label="Period",
                    on_change=self._period_changed,
                ).classes("w-36 sm:w-40")

            with ui.card().classes("w-full"):
                ui.label("Active Screen Intersection").classes("text-h6")
                columns = [
                    {"name": "activity", "label": "Activity", "field": "activity"},
                    {"name": "activity_time", "label": "Activity Time", "field": "activity_time"},
                    {"name": "screen_time", "label": "Screen Time", "field": "screen_time"},
                    {"name": "without_screen", "label": "Without Screen", "field": "without_screen"},
                    {"name": "screen_share", "label": "Screen Share", "field": "screen_share"},
                ]
                self.summary_table = ui.table(
                    columns=columns,
                    rows=[],
                    pagination=15,
                ).classes("w-full")
                configure_responsive_table(
                    self.summary_table,
                    columns,
                    mobile_columns=["activity", "screen_time", "screen_share"],
                )

            with ui.card().classes("w-full"):
                ui.label("Screen Time by Activity").classes("text-h6")
                self.chart = ui.echart(
                    self._empty_options("Choose activities")
                ).classes("bh-chart w-full h-80")

            with ui.card().classes("w-full"):
                ui.label("Screen Share Trend").classes("text-h6")
                self.trend_chart = ui.echart(
                    self._empty_options("Choose activities")
                ).classes("bh-chart w-full h-80")

    def update(self, timeline: Timeline):
        self.timeline = timeline
        options = self._activity_options(timeline)
        using_sidebar_activities = bool(timeline.query.activities)
        self.activity_select.visible = not using_sidebar_activities
        self.clear_button.visible = not using_sidebar_activities
        self.activity_select.update()
        self.clear_button.update()

        if not using_sidebar_activities:
            self.activity_select.set_options(options)

            selected = [activity for activity in self.selected_activities if activity in options]
            if selected != self.selected_activities:
                self.selected_activities = selected
                self.activity_select.set_value(selected)

        self._render()

    def _activities_changed(self, event):
        self.selected_activities = list(event.value or [])
        self._render()

    def _period_changed(self, event):
        self.period = event.value
        self._render()

    def _clear(self):
        self.selected_activities = []
        self.activity_select.set_value([])
        self._render()

    def _render(self):
        activities = self._effective_activities()
        if self.timeline is None or not activities:
            self.summary_table.rows = []
            self.summary_table.update()
            self._set_options(self.chart, self._empty_options("Choose activities"))
            self._set_options(self.trend_chart, self._empty_options("Choose activities"))
            return

        df = active_screen_intersection(self.timeline, activities)
        trend_df = active_screen_intersection_over_time(
            self.timeline,
            activities,
            PERIODS[self.period], # type: ignore[arg-type]
        )

        self.summary_table.rows = self._table_rows(df)
        self.summary_table.update()
        self._set_options(self.chart, self._chart_options(df))
        self._set_options(self.trend_chart, self._trend_options(trend_df, PERIODS[self.period]))

    def _effective_activities(self) -> list[str]:
        if self.timeline is not None and self.timeline.query.activities:
            return sorted(self.timeline.query.activities)
        return self.selected_activities

    def _activity_options(self, timeline: Timeline) -> list[str]:
        query = Query(
            start=timeline.query.start,
            end=timeline.query.end,
            sources=frozenset({DeviceSource.EMBED}),
            weekday=timeline.query.weekday,
        )
        return Timeline(timeline.repo, query).metadata.activities

    @staticmethod
    def _table_rows(df: pl.DataFrame) -> list[dict[str, str]]:
        if df.is_empty():
            return []

        return [
            {
                "activity": f"{row['name']} · {row['category']}",
                "activity_time": human_duration(row["activity_seconds"]),
                "screen_time": human_duration(row["screen_seconds"]),
                "without_screen": human_duration(row["activity_without_screen_seconds"]),
                "screen_share": f"{row['activity_screen_percent']:.1f}%",
            }
            for row in df.to_dicts()
        ]

    @staticmethod
    def _chart_options(df: pl.DataFrame) -> dict:
        if df.is_empty():
            return ScreenTimeIntersectionView._empty_options("No overlap")

        rows = df.with_columns(
            activity=pl.concat_str(
                [
                    pl.col("name").fill_null(""),
                    pl.lit(" · "),
                    pl.col("category").fill_null(""),
                ]
            ),
            screen_hours=pl.col("screen_seconds") / 3600,
            without_screen_hours=pl.col("activity_without_screen_seconds") / 3600,
        ).to_dicts()

        return responsive_chart_options({
            "tooltip": {
                "trigger": "axis",
                "axisPointer": {"type": "shadow"},
                ":valueFormatter": "value => `${value.toFixed(2)} h`",
            },
            "legend": {"top": 0},
            "grid": {
                "left": 56,
                "right": 24,
                "top": 48,
                "bottom": 72,
            },
            "xAxis": {
                "type": "category",
                "axisLabel": {"rotate": 25},
                "data": [row["activity"] for row in rows],
            },
            "yAxis": {
                "type": "value",
                "name": "hours",
            },
            "series": [
                {
                    "name": "Screen",
                    "type": "bar",
                    "stack": "activity",
                    "data": [round(row["screen_hours"], 3) for row in rows],
                },
                {
                    "name": "Without screen",
                    "type": "bar",
                    "stack": "activity",
                    "data": [round(row["without_screen_hours"], 3) for row in rows],
                },
            ],
        })

    @staticmethod
    def _trend_options(df: pl.DataFrame, period: str) -> dict:
        if df.is_empty():
            return ScreenTimeIntersectionView._empty_options("No screen share")

        df = (
            df.with_columns(
                activity=pl.concat_str(
                    [
                        pl.col("name").fill_null(""),
                        pl.lit(" · "),
                        pl.col("category").fill_null(""),
                    ]
                ),
                period_label=ScreenTimeIntersectionView._period_label(period),
            )
            .sort(["period", "activity"])
        )
        periods = df["period_label"].unique(maintain_order=True).to_list()
        activities = df["activity"].unique(maintain_order=True).to_list()

        return responsive_chart_options({
            "tooltip": {
                "trigger": "axis",
                ":valueFormatter": "value => `${value.toFixed(1)}%`",
            },
            "legend": {
                "type": "scroll",
                "top": 0,
            },
            "grid": {
                "left": 56,
                "right": 24,
                "top": 56,
                "bottom": 56,
            },
            "xAxis": {
                "type": "category",
                "boundaryGap": False,
                "data": periods,
            },
            "yAxis": {
                "type": "value",
                "name": "%",
                "min": 0,
                "max": 100,
            },
            "series": [
                {
                    "name": activity,
                    "type": "line",
                    "smooth": True,
                    "showSymbol": False,
                    "data": [
                        round(values_by_period.get(period_label, 0.0), 1)
                        for period_label in periods
                    ],
                }
                for activity in activities
                for values_by_period in [
                    dict(
                        zip(
                            df.filter(pl.col("activity") == activity)["period_label"].to_list(),
                            df.filter(pl.col("activity") == activity)["activity_screen_percent"].to_list(),
                            strict=True,
                        )
                    )
                ]
            ],
        })

    @staticmethod
    def _period_label(period: str) -> pl.Expr:
        match period:
            case "week":
                return pl.col("period").dt.strftime("%G-W%V")
            case "month":
                return pl.col("period").dt.strftime("%Y-%m")
            case "year":
                return pl.col("period").dt.strftime("%Y")
            case _:
                return pl.col("period").dt.strftime("%Y-%m-%d")

    @staticmethod
    def _empty_options(message: str) -> dict:
        return {
            "title": {
                "text": message,
                "left": "center",
                "top": "middle",
                "textStyle": {"fontSize": 16, "fontWeight": "normal"},
            },
            "xAxis": {"show": False},
            "yAxis": {"show": False},
            "series": [],
        }

    @staticmethod
    def _set_options(chart, options: dict):
        chart.options.clear()
        chart.options.update(options)
        chart.update()
