from nicegui import ui

from timeline.api.timeline import Timeline
from timeline.statistics.tools import human_duration

class SummaryView:

    def __init__(self):
        with ui.card().classes("w-full"):
            ui.label("Summary").classes("text-h6")

            with ui.grid().classes("grid-cols-2 lg:grid-cols-4 gap-x-4 gap-y-2 w-full"):
                self.sessions = ui.label()
                self.total = ui.label()

                self.average = ui.label()
                self.median = ui.label()

    def update(self, timeline: Timeline):
        stats = timeline.statistics.chunks

        self.sessions.set_text(
            f"Sessions: {stats.sessions}"
        )

        self.total.set_text(
            f"Total: {human_duration(stats.total_seconds)}"
        )

        self.average.set_text(
            f"Average: {human_duration(stats.average_seconds)}"
        )

        self.median.set_text(
            f"Median: {human_duration(stats.median_seconds)}"
        )
