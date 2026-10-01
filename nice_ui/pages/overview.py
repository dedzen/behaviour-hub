from __future__ import annotations

from dataclasses import dataclass

import polars as pl
from nicegui import ui

from nice_ui.responsive import responsive_chart_options
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource
from timeline.statistics.tools import human_duration


@dataclass(frozen=True, slots=True)
class OverviewMetrics:
    tracked_seconds: int
    sessions: int
    average_seconds: float
    screen_seconds: int


def screen_seconds(timeline: Timeline) -> int:
    phone = (
        Timeline(timeline.repo)
        .between(timeline.query.start, timeline.query.end)
        .source(DeviceSource.PHONE)
        .category("Screen")
        .activity("Screen on")
    )
    return phone.statistics.chunks.total_seconds


def overview_metrics(timeline: Timeline) -> OverviewMetrics:
    stats = timeline.statistics.chunks
    return OverviewMetrics(
        tracked_seconds=stats.total_seconds,
        sessions=stats.sessions,
        average_seconds=stats.average_seconds,
        screen_seconds=screen_seconds(timeline),
    )


def delta_text(current: float, previous: float, *, available: bool) -> str:
    if not available:
        return "No comparison"
    if previous == 0:
        return "No prior data" if current else "No change"
    change = (current - previous) / previous * 100
    arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
    return f"{arrow} {abs(change):.0f}% vs previous period"


class KpiCard:
    def __init__(self, label: str, icon: str):
        with ui.card().classes("bh-card bh-kpi-card w-full") as self.card:
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(label).classes("text-caption text-grey-7")
                ui.icon(icon).classes("text-primary text-xl")
            self.value = ui.label("—").classes("bh-kpi-value")
            self.delta = ui.label("No comparison").classes("text-caption text-grey-6")

    def update(self, value: str, delta: str) -> None:
        self.value.set_text(value)
        self.delta.set_text(delta)


class OverviewView:
    def __init__(self):
        with ui.column().classes("w-full gap-4"):
            with ui.row().classes("w-full items-end justify-between gap-2"):
                with ui.column().classes("gap-0"):
                    ui.label("Overview").classes("text-h5")
                    self.range_label = ui.label().classes("text-caption text-grey-7")

            with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3"):
                self.tracked = KpiCard("Tracked time", "schedule")
                self.sessions = KpiCard("Sessions", "timelapse")
                self.average = KpiCard("Average session", "avg_time")
                self.screen = KpiCard("Phone screen time", "phone_android")

            with ui.row().classes("w-full gap-4 items-stretch flex-col xl:flex-row"):
                with ui.card().classes("bh-card flex-1 min-w-0"):
                    ui.label("Top activities").classes("text-h6")
                    self.empty = ui.label(
                        "No tracked activity in this range. Adjust filters or import data."
                    ).classes("bh-empty-state")
                    self.top_list = ui.column().classes("w-full gap-2")
                with ui.card().classes("bh-card flex-[2] min-w-0"):
                    ui.label("Tracked time trend").classes("text-h6")
                    self.chart = ui.echart(self._empty_chart()).classes(
                        "bh-chart-compact w-full h-72"
                    )

    def update(
        self,
        timeline: Timeline,
        previous: Timeline | None,
        *,
        range_label: str,
    ) -> None:
        current = overview_metrics(timeline)
        prior = overview_metrics(previous) if previous is not None else OverviewMetrics(0, 0, 0, 0)
        available = previous is not None
        self.range_label.set_text(range_label)
        self.tracked.update(
            human_duration(current.tracked_seconds),
            delta_text(current.tracked_seconds, prior.tracked_seconds, available=available),
        )
        self.sessions.update(
            str(current.sessions), delta_text(current.sessions, prior.sessions, available=available)
        )
        self.average.update(
            human_duration(current.average_seconds),
            delta_text(current.average_seconds, prior.average_seconds, available=available),
        )
        self.screen.update(
            human_duration(current.screen_seconds),
            delta_text(current.screen_seconds, prior.screen_seconds, available=available),
        )
        self._update_top_activities(timeline)
        self.chart.options.clear()
        self.chart.options.update(self._trend_options(timeline))
        self.chart.update()

    def _update_top_activities(self, timeline: Timeline) -> None:
        activity = timeline.statistics.chunks.by_activity().head(5)
        self.top_list.clear()
        self.empty.set_visibility(activity.is_empty())
        self.top_list.set_visibility(not activity.is_empty())
        if activity.is_empty():
            return
        total = max(1, int(activity["total_seconds"].sum()))
        with self.top_list:
            for row in activity.to_dicts():
                seconds = int(row["total_seconds"])
                label = row.get("name") or "Untitled"
                category = row.get("category") or "Uncategorised"
                with ui.column().classes("w-full gap-1"):
                    with ui.row().classes("w-full items-center justify-between gap-2"):
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(label).classes("text-body2 font-medium truncate")
                            ui.label(category).classes("text-caption text-grey-6 truncate")
                        ui.label(human_duration(seconds)).classes("text-body2 whitespace-nowrap")
                    ui.linear_progress(value=seconds / total).props("rounded size=6px")

    @staticmethod
    def _empty_chart() -> dict:
        return {"title": {"text": "No tracked time", "left": "center", "top": "middle"}}

    def _trend_options(self, timeline: Timeline) -> dict:
        df = timeline.statistics.chunks.by_day()
        if df.is_empty():
            return self._empty_chart()
        df = df.with_columns(
            day=pl.col("day").cast(pl.Date).dt.strftime("%b %d"),
            hours=pl.col("total_seconds") / 3600,
        )
        return responsive_chart_options({
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 48, "right": 20, "top": 20, "bottom": 42},
            "xAxis": {"type": "category", "data": df["day"].to_list()},
            "yAxis": {"type": "value", "name": "hours"},
            "series": [{
                "name": "Tracked time", "type": "bar",
                "data": [round(value, 2) for value in df["hours"].to_list()],
                "itemStyle": {"borderRadius": [5, 5, 0, 0]},
            }],
        })
