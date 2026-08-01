from nicegui import ui
import polars as pl

from timeline.api.timeline import Timeline
from timeline.statistics.tools import human_duration

class ActivityView:

    def __init__(self):
        self.card = ui.card().classes("w-full")
        with self.card:
            ui.label("Activity Statistics").classes("text-h6")

            self.table = ui.table(
                columns=[
                    {
                        "name": "name",
                        "label": "Activity",
                        "field": "name",
                    },
                    {
                        "name": "sessions",
                        "label": "Sessions",
                        "field": "sessions",
                    },
                    {
                        "name": "total",
                        "label": "Total",
                        "field": "total",
                    },
                    {
                        "name": "average",
                        "label": "Average",
                        "field": "average",
                    },
                    {
                        "name": "median",
                        "label": "Median",
                        "field": "median",
                    },
                ],
                rows=[],
                pagination=20,
            ).classes("w-full")
    def set_visible(self, visible: bool):
        self.card.visible = visible
        self.card.update()
    def update(
        self,
        timeline: Timeline,
    ):
        df = (
            timeline.statistics.chunks.by_activity()
            .select(
                "name",
                "sessions",
                total=pl.col("total_seconds").map_elements(human_duration),
                average=pl.col("average_seconds").map_elements(human_duration),
                median=pl.col("median_seconds").map_elements(human_duration),
            )
        )

        self.table.rows = df.to_dicts()
        self.table.update()