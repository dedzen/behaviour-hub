from __future__ import annotations

from nicegui import ui
import polars as pl

from timeline.api.timeline import Timeline
from nice_ui.responsive import responsive_chart_options


PERIODS = {
    "Day": "day",
    "Week": "week",
    "Month": "month",
    "Year": "year",
}


class PlotsView:
    def __init__(self):
        self.timeline: Timeline | None = None
        self.period = "Day"

        with ui.column().classes("w-full gap-3 sm:gap-4"):
            with ui.row().classes("w-full justify-end"):
                ui.select(
                    list(PERIODS),
                    value=self.period,
                    label="Period",
                    on_change=self._period_changed,
                ).classes("w-36 sm:w-40")

            with ui.card().classes("w-full"):
                ui.label("Activity Time Share").classes("text-h6")
                self.share_chart = ui.echart(
                    self._empty_options("No activity time")
                ).classes("bh-chart w-full h-96")

            with ui.card().classes("w-full"):
                ui.label("Total Tracked Time").classes("text-h6")
                self.total_chart = ui.echart(
                    self._empty_options("No tracked time")
                ).classes("bh-chart-compact w-full h-80")

            with ui.card().classes("w-full"):
                ui.label("Top Activity Composition").classes("text-h6")
                self.stacked_chart = ui.echart(
                    self._empty_options("No activity composition")
                ).classes("bh-chart w-full h-96")

            with ui.card().classes("w-full"):
                ui.label("Activity Time Trend").classes("text-h6")
                self.trend_chart = ui.echart(
                    self._empty_options("No activity trend")
                ).classes("bh-chart w-full h-96")

    def update(self, timeline: Timeline):
        self.timeline = timeline

        self._set_options(self.share_chart, self._share_options(timeline))

        self._set_options(self.total_chart, self._total_options(timeline))

        self._set_options(self.stacked_chart, self._stacked_options(timeline))

        self._set_options(self.trend_chart, self._trend_options(timeline))

    def _period_changed(self, event):
        self.period = event.value
        if self.timeline is not None:
            self.update(self.timeline)

    def _share_options(self, timeline: Timeline) -> dict:
        share = timeline.analytics.chunks.share(by=["category", "name"]).head(12)
        if share.is_empty():
            return self._empty_options("No activity time")

        df = (
            share
            .with_columns(
                activity=pl.concat_str(
                    [
                        pl.col("name").fill_null(""),
                        pl.lit(" · "),
                        pl.col("category").fill_null(""),
                    ]
                ),
                hours=pl.col("total_seconds") / 3600,
            )
        )

        return responsive_chart_options({
            "tooltip": {
                "trigger": "item",
                ":valueFormatter": "value => `${value.toFixed(2)} h`",
            },
            "legend": {
                "type": "scroll",
                "orient": "vertical",
                "right": 8,
                "top": 20,
                "bottom": 20,
            },
            "series": [
                {
                    "type": "pie",
                    "radius": ["35%", "70%"],
                    "center": ["38%", "52%"],
                    "avoidLabelOverlap": True,
                    "data": [
                        {
                            "name": row["activity"],
                            "value": row["hours"],
                        }
                        for row in df.select("activity", "hours").to_dicts()
                    ],
                }
            ],
        }, pie=True)

    def _total_options(self, timeline: Timeline) -> dict:
        period = PERIODS[self.period]
        totals = timeline.analytics.chunks.over_time(period, by=None) # type: ignore
        if totals.is_empty():
            return self._empty_options("No tracked time")

        df = (
            totals
            .with_columns(
                period_label=self._period_label(period),
                hours=pl.col("total_seconds") / 3600,
            )
            .sort("period")
        )

        return responsive_chart_options({
            "tooltip": {
                "trigger": "axis",
                ":valueFormatter": "value => `${value.toFixed(2)} h`",
            },
            "grid": {
                "left": 48,
                "right": 24,
                "top": 24,
                "bottom": 40,
            },
            "xAxis": {
                "type": "category",
                "data": df["period_label"].to_list(),
            },
            "yAxis": {
                "type": "value",
                "name": "hours",
            },
            "series": [
                {
                    "name": "Tracked time",
                    "type": "bar",
                    "data": [round(value, 2) for value in df["hours"].to_list()],
                }
            ],
        })

    def _stacked_options(self, timeline: Timeline) -> dict:
        period = PERIODS[self.period]
        share = timeline.analytics.chunks.share(by=["category", "name"]).head(6)

        if share.is_empty():
            return self._empty_options("No activity composition")

        top_activities = share.select(["category", "name"])
        df = (
            timeline.analytics.chunks.over_time(period, by=["category", "name"]) #type: ignore
            .join(top_activities, on=["category", "name"], how="inner")
            .with_columns(
                activity=pl.concat_str(
                    [
                        pl.col("name").fill_null(""),
                        pl.lit(" · "),
                        pl.col("category").fill_null(""),
                    ]
                ),
                period_label=self._period_label(period),
                hours=pl.col("total_seconds") / 3600,
            )
            .sort(["period", "activity"])
        )

        if df.is_empty():
            return self._empty_options("No activity composition")

        periods = df["period_label"].unique(maintain_order=True).to_list()
        activities = df["activity"].unique(maintain_order=True).to_list()

        return responsive_chart_options({
            "tooltip": {
                "trigger": "axis",
                "axisPointer": {"type": "shadow"},
                ":valueFormatter": "value => `${value.toFixed(2)} h`",
            },
            "legend": {
                "type": "scroll",
                "top": 0,
            },
            "grid": {
                "left": 48,
                "right": 24,
                "top": 56,
                "bottom": 40,
            },
            "xAxis": {
                "type": "category",
                "data": periods,
            },
            "yAxis": {
                "type": "value",
                "name": "hours",
            },
            "series": self._period_activity_series(
                df,
                periods,
                activities,
                chart_type="bar",
                stack="total",
            ),
        })

    def _trend_options(self, timeline: Timeline) -> dict:
        period = PERIODS[self.period]
        share = timeline.analytics.chunks.share(by=["category", "name"]).head(6)

        if share.is_empty():
            return self._empty_options("No activity trend")

        top_activities = share.select(["category", "name"])
        df = (
            timeline.analytics.chunks.over_time(period, by=["category", "name"]) #type: ignore
            .join(top_activities, on=["category", "name"], how="inner")
            .with_columns(
                activity=pl.concat_str(
                    [
                        pl.col("name").fill_null(""),
                        pl.lit(" · "),
                        pl.col("category").fill_null(""),
                    ]
                ),
                period_label=self._period_label(period),
                hours=pl.col("total_seconds") / 3600,
            )
            .sort(["period", "activity"])
        )

        if df.is_empty():
            return self._empty_options("No activity trend")

        periods = df["period_label"].unique(maintain_order=True).to_list()
        activities = df["activity"].unique(maintain_order=True).to_list()

        return responsive_chart_options({
            "tooltip": {
                "trigger": "axis",
                ":valueFormatter": "value => `${value.toFixed(2)} h`",
            },
            "legend": {
                "type": "scroll",
                "top": 0,
            },
            "grid": {
                "left": 48,
                "right": 24,
                "top": 56,
                "bottom": 40,
            },
            "xAxis": {
                "type": "category",
                "boundaryGap": False,
                "data": periods,
            },
            "yAxis": {
                "type": "value",
                "name": "hours",
            },
            "series": self._period_activity_series(
                df,
                periods,
                activities,
                chart_type="line",
                smooth=True,
                show_symbol=False,
            ),
        })

    @staticmethod
    def _period_activity_series(
        df: pl.DataFrame,
        periods: list[str],
        activities: list[str],
        *,
        chart_type: str,
        stack: str | None = None,
        smooth: bool = False,
        show_symbol: bool = True,
    ) -> list[dict]:
        series = []

        for activity in activities:
            activity_df = df.filter(pl.col("activity") == activity)
            values_by_period = dict(
                zip(
                    activity_df["period_label"].to_list(),
                    activity_df["hours"].to_list(),
                    strict=True,
                )
            )
            options = {
                "name": activity,
                "type": chart_type,
                "data": [
                    round(values_by_period.get(period_label, 0), 2)
                    for period_label in periods
                ],
            }

            if stack is not None:
                options["stack"] = stack

            if chart_type == "line":
                options["smooth"] = smooth
                options["showSymbol"] = show_symbol

            series.append(options)

        return series

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
                "top": "center",
                "textStyle": {"color": "#6b7280", "fontSize": 14},
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
