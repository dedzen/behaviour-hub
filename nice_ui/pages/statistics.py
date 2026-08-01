from __future__ import annotations

from nicegui import ui

from timeline.api.timeline import Timeline
from nice_ui.pages.summary import SummaryView
from nice_ui.pages.by_activity import ActivityView
from nice_ui.pages.by_day import DailyView


class StatisticsView:
    def __init__(self):
        with ui.column().classes("w-full gap-4"):
            self.summary = SummaryView()
            self.by_activity = ActivityView()
            self.by_day = DailyView()

    def update(self, timeline: Timeline):
        self.summary.update(timeline)

        activity = timeline.statistics.chunks.by_activity()
        self.by_activity.set_visible(len(activity) > 1)
        if len(activity) > 1:
            self.by_activity.update(timeline)

        daily = timeline.statistics.chunks.by_day()
        self.by_day.set_visible(len(daily) > 1)
        if len(daily) > 1:
            self.by_day.update(timeline)
