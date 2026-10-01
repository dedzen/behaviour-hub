from __future__ import annotations

from nicegui import ui
import polars as pl

from timeline.api.timeline import Timeline
from timeline.statistics.tools import human_duration
from nice_ui.responsive import configure_responsive_table


class AnalyticsView:
    def __init__(self):
        with ui.column().classes("w-full gap-4"):
            self.share = AnalyticsTable(
                "Time Share by Activity",
                [
                    ("name", "Activity"),
                    ("category", "Category"),
                    ("total", "Total"),
                    ("percent", "Share"),
                ],
                mobile_columns=["name", "total", "percent"],
            )
            self.day_category = AnalyticsTable(
                "Daily Activity Mix",
                [
                    ("period", "Day"),
                    ("name", "Activity"),
                    ("category", "Category"),
                    ("sessions", "Sessions"),
                    ("total", "Total"),
                    ("average", "Average"),
                ],
                mobile_columns=["period", "name", "total"],
            )
            self.rolling = AnalyticsTable(
                "Rolling Daily Activity Time",
                [
                    ("period", "Day"),
                    ("name", "Activity"),
                    ("category", "Category"),
                    ("total", "Total"),
                    ("rolling_average", "Rolling Avg"),
                ],
                mobile_columns=["period", "name", "rolling_average"],
            )
            self.transitions = AnalyticsTable(
                "Short-gap Activity Transitions",
                [
                    ("from_activity", "From"),
                    ("to_activity", "To"),
                    ("transitions", "Transitions"),
                    ("average_gap", "Avg Gap"),
                    ("to_average", "Next Avg"),
                ],
                mobile_columns=["from_activity", "to_activity", "transitions"],
            )

    def update(self, timeline: Timeline):
        analytics = timeline.analytics.chunks
        share = analytics.share(by=["category", "name"])
        if share.is_empty():
            empty = pl.DataFrame()
            self.share.update(empty)
            self.day_category.update(empty)
            self.rolling.update(empty)
            self.transitions.update(empty)
            return

        self.share.update(
            share
            .select(
                "name",
                "category",
                total=pl.col("total_seconds").map_elements(human_duration),
                percent=pl.col("percent").round(1).cast(pl.String) + "%",
            )
        )

        self.day_category.update(
            analytics.over_time("day", by=["category", "name"])
            .select(
                "name",
                "category",
                "sessions",
                period=pl.col("period").dt.strftime("%Y-%m-%d"),
                total=pl.col("total_seconds").map_elements(human_duration),
                average=pl.col("average_seconds").map_elements(human_duration),
            )
        )

        self.rolling.update(
            analytics.rolling("day", window=7, by=["category", "name"])
            .select(
                "name",
                "category",
                period=pl.col("period").dt.strftime("%Y-%m-%d"),
                total=pl.col("total_seconds").map_elements(human_duration),
                rolling_average=pl.col("total_seconds_rolling_average")
                .map_elements(human_duration),
            )
        )

        transitions = analytics.transitions(max_gap_seconds=15 * 60)

        if transitions.is_empty():
            self.transitions.update(pl.DataFrame())
            return

        self.transitions.update(
            transitions
            .with_columns(
                from_activity=pl.concat_str(
                    [
                        pl.col("from_category").fill_null(""),
                        pl.lit(" / "),
                        pl.col("from_name").fill_null(""),
                    ]
                ),
                to_activity=pl.concat_str(
                    [
                        pl.col("to_category").fill_null(""),
                        pl.lit(" / "),
                        pl.col("to_name").fill_null(""),
                    ]
                ),
            )
            .select(
                "from_activity",
                "to_activity",
                "transitions",
                average_gap=pl.col("average_gap_seconds").map_elements(human_duration),
                to_average=pl.col("to_average_seconds").map_elements(human_duration),
            )
        )


class AnalyticsTable:
    def __init__(
        self,
        title: str,
        columns: list[tuple[str, str]],
        mobile_columns: list[str] | None = None,
    ):
        self.card = ui.card().classes("w-full")
        with self.card:
            ui.label(title).classes("text-h6")
            table_columns = [
                {
                    "name": name,
                    "label": label,
                    "field": name,
                }
                for name, label in columns
            ]
            self.table = ui.table(
                columns=table_columns,
                rows=[],
                pagination=15,
            ).classes("w-full")
            configure_responsive_table(
                self.table,
                table_columns,
                mobile_columns=mobile_columns or [columns[0][0], columns[-1][0]],
            )

    def update(self, df: pl.DataFrame):
        self.card.visible = not df.is_empty()
        self.table.rows = df.to_dicts()
        self.table.update()
        self.card.update()
