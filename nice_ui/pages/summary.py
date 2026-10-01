from nicegui import ui

from timeline.api.timeline import Timeline
from timeline.statistics.tools import human_duration

class SummaryView:

    def __init__(self):
        with ui.column().classes("w-full gap-2"):
            ui.label("Summary").classes("text-h6")
            with ui.grid().classes("grid-cols-2 lg:grid-cols-4 gap-3 w-full"):
                self.sessions = self._metric("Sessions")
                self.total = self._metric("Total time")
                self.average = self._metric("Average session")
                self.median = self._metric("Median session")

    @staticmethod
    def _metric(label: str):
        with ui.card().classes("bh-card w-full"):
            ui.label(label).classes("text-caption text-grey-7")
            return ui.label().classes("text-h6")

    def update(self, timeline: Timeline):
        stats = timeline.statistics.chunks

        self.sessions.set_text(
            str(stats.sessions)
        )

        self.total.set_text(
            human_duration(stats.total_seconds)
        )

        self.average.set_text(
            human_duration(stats.average_seconds)
        )

        self.median.set_text(
            human_duration(stats.median_seconds)
        )
