from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import polars as pl

Metric = Literal[
    "sessions",
    "total_seconds",
    "average_seconds",
    "median_seconds",
    "minimum_seconds",
    "maximum_seconds",
]
Period = Literal["hour", "day", "week", "month", "year"]

DEFAULT_METRICS: tuple[Metric, ...] = (
    "sessions",
    "total_seconds",
    "average_seconds",
)
ACTIVITY_COLUMNS: tuple[str, str] = ("category", "name")
PERIOD_EVERY: dict[Period, str] = {
    "hour": "1h",
    "day": "1d",
    "week": "1w",
    "month": "1mo",
    "year": "1y",
}


class ChunkAnalytics:
    def __init__(self, df: pl.DataFrame) -> None:
        self.df = df

    def summarize(
        self,
        by: str | Sequence[str] | None = ACTIVITY_COLUMNS,
        *,
        metrics: Sequence[Metric] = DEFAULT_METRICS,
        sort_by: str = "total_seconds",
        descending: bool = True,
    ) -> pl.DataFrame:
        """Aggregate selected metrics for the current timeline slice."""

        if self.df.is_empty():
            return pl.DataFrame()

        group_columns = self._columns(by)
        aggregations = self._metric_expressions(metrics)

        if not group_columns:
            return self.df.select(aggregations)

        result = self.df.group_by(group_columns).agg(aggregations)

        if sort_by in result.columns:
            result = result.sort(sort_by, descending=descending)

        return result

    def over_time(
        self,
        period: Period = "day",
        *,
        by: str | Sequence[str] | None = None,
        metrics: Sequence[Metric] = DEFAULT_METRICS,
        sort: bool = True,
    ) -> pl.DataFrame:
        """Aggregate metrics by time period, optionally split by other columns."""

        if self.df.is_empty():
            return pl.DataFrame()

        group_columns = ["period", *self._columns(by)]

        result = (
            self.df
            .with_columns(
                pl.col("start_timestamp")
                .dt.truncate(PERIOD_EVERY[period])
                .alias("period")
            )
            .group_by(group_columns)
            .agg(self._metric_expressions(metrics))
        )

        if sort:
            result = result.sort(group_columns)

        return result

    def share(
        self,
        by: str | Sequence[str] = ACTIVITY_COLUMNS,
        *,
        metric: Literal["total_seconds", "sessions"] = "total_seconds",
    ) -> pl.DataFrame:
        """Calculate each group's share of total duration or session count."""

        metric_expr = {
            "total_seconds": pl.sum("duration_seconds"),
            "sessions": pl.len(),
        }[metric]

        if self.df.is_empty():
            return pl.DataFrame()

        group_columns = self._columns(by)
        total = self.df.select(metric_expr).item()

        if total == 0:
            return pl.DataFrame()

        return (
            self.df
            .group_by(group_columns)
            .agg(metric_expr.alias(metric))
            .with_columns((pl.col(metric) / total * 100).alias("percent"))
            .sort(metric, descending=True)
        )

    def pivot(
        self,
        *,
        index: str | Sequence[str] = "category",
        columns: str | Sequence[str] = "name",
        values: Literal["total_seconds", "sessions"] = "total_seconds",
    ) -> pl.DataFrame:
        """Build a generic matrix such as category by activity or day by category."""

        if self.df.is_empty():
            return pl.DataFrame()

        index_columns = self._columns(index)
        column_columns = self._columns(columns)
        value_expr = {
            "total_seconds": pl.sum("duration_seconds"),
            "sessions": pl.len(),
        }[values]

        return (
            self.df
            .group_by([*index_columns, *column_columns])
            .agg(value_expr.alias(values))
            .pivot(
                index=index_columns,
                column_naming=column_columns,
                values=values,
                aggregate_function="first",
            ) # type: ignore
            .fill_null(0)
        )

    def rolling(
        self,
        period: Period = "day",
        *,
        window: int = 7,
        by: str | Sequence[str] | None = None,
        metric: Literal["total_seconds", "sessions"] = "total_seconds",
    ) -> pl.DataFrame:
        """Aggregate over time and add a rolling average of the selected metric."""

        value_column = metric
        time_series = self.over_time(period, by=by, metrics=(metric,))

        if time_series.is_empty():
            return time_series

        sort_columns = [*self._columns(by), "period"]
        partition_columns = self._columns(by)

        if partition_columns:
            return (
                time_series
                .sort(sort_columns)
                .with_columns(
                    pl.col(value_column)
                    .rolling_mean(window_size=window, min_samples=1)
                    .over(partition_columns)
                    .alias(f"{value_column}_rolling_average")
                )
            )

        return (
            time_series
            .sort("period")
            .with_columns(
                pl.col(value_column)
                .rolling_mean(window_size=window, min_samples=1)
                .alias(f"{value_column}_rolling_average")
            )
        )

    def transitions(
        self,
        by: str | Sequence[str] = ACTIVITY_COLUMNS,
        *,
        max_gap_seconds: int | None = None,
        include_same: bool = False,
    ) -> pl.DataFrame:
        """Aggregate adjacent chunk transitions by any chunk identity columns."""

        sequenced = self._sequenced(by)

        if sequenced.is_empty():
            return pl.DataFrame()

        from_columns = [f"from_{column}" for column in self._columns(by)]
        to_columns = [f"to_{column}" for column in self._columns(by)]

        transitions = sequenced.filter(pl.col(from_columns[0]).is_not_null())

        if max_gap_seconds is not None:
            transitions = transitions.filter(
                (pl.col("gap_seconds") >= 0)
                & (pl.col("gap_seconds") <= max_gap_seconds)
            )

        if not include_same:
            changed = pl.any_horizontal(
                pl.col(from_column) != pl.col(to_column)
                for from_column, to_column in zip(from_columns, to_columns, strict=True)
            )
            transitions = transitions.filter(changed)

        if transitions.is_empty():
            return transitions.select(
                [*from_columns, *to_columns, "gap_seconds", "duration_seconds"]
            )

        return (
            transitions
            .group_by([*from_columns, *to_columns])
            .agg(
                pl.len().alias("transitions"),
                pl.mean("gap_seconds").alias("average_gap_seconds"),
                pl.median("gap_seconds").alias("median_gap_seconds"),
                pl.sum("duration_seconds").alias("to_total_seconds"),
                pl.mean("duration_seconds").alias("to_average_seconds"),
            )
            .sort("transitions", descending=True)
        )

    def compare(
        self,
        other: ChunkAnalytics | pl.DataFrame,
        by: str | Sequence[str] | None = ACTIVITY_COLUMNS,
        *,
        metric: Metric = "total_seconds",
        labels: tuple[str, str] = ("current", "other"),
    ) -> pl.DataFrame:
        """Compare this chunk slice against another analytics object or dataframe."""

        other_df = other.df if isinstance(other, ChunkAnalytics) else other
        group_columns = self._columns(by)

        left = self._metric_frame(self.df, group_columns, metric, labels[0])
        right = self._metric_frame(other_df, group_columns, metric, labels[1])

        on = group_columns or ["_comparison"]
        if not group_columns:
            left = left.with_columns(pl.lit("all").alias("_comparison"))
            right = right.with_columns(pl.lit("all").alias("_comparison"))

        result = (
            left
            .join(right, on=on, how="full", coalesce=True)
            .fill_null(0)
            .with_columns(
                (pl.col(labels[0]) - pl.col(labels[1])).alias("delta"),
                pl.when(pl.col(labels[1]) == 0)
                .then(None)
                .otherwise((pl.col(labels[0]) - pl.col(labels[1])) / pl.col(labels[1]) * 100)
                .alias("delta_percent"),
            )
            .sort("delta", descending=True)
        )

        if not group_columns:
            return result.drop("_comparison")

        return result

    def _sequenced(self, by: str | Sequence[str]) -> pl.DataFrame:
        columns = self._columns(by)

        if self.df.is_empty() or not columns:
            return pl.DataFrame()

        return (
            self.df
            .sort("start_timestamp")
            .with_columns(
                [
                    pl.col(column).shift(1).alias(f"from_{column}")
                    for column in columns
                ]
                + [
                    pl.col(column).alias(f"to_{column}")
                    for column in columns
                ]
                + [
                    pl.col("end_timestamp").shift(1).alias("previous_end_timestamp"),
                    pl.col("duration_seconds").shift(1).alias("previous_duration_seconds"),
                ]
            )
            .with_columns(
                (
                    pl.col("start_timestamp") - pl.col("previous_end_timestamp")
                ).dt.total_seconds().alias("gap_seconds")
            )
        )

    def _metric_frame(
        self,
        df: pl.DataFrame,
        by: list[str],
        metric: Metric,
        alias: str,
    ) -> pl.DataFrame:
        expression = self._metric_expressions((metric,))[0].alias(alias)

        if df.is_empty():
            if by:
                return pl.DataFrame(
                    {
                        **{
                            column: pl.Series(
                                column,
                                [],
                                dtype=self._empty_column_dtype(df, column),
                            )
                            for column in by
                        },
                        alias: pl.Series(alias, [], dtype=self._metric_dtype(metric)),
                    }
                )
            return pl.DataFrame({alias: [0]})

        if by:
            return df.group_by(by).agg(expression)

        return df.select(expression)

    @staticmethod
    def _columns(columns: str | Sequence[str] | None) -> list[str]:
        if columns is None:
            return []

        if isinstance(columns, str):
            return [columns]

        return list(columns)

    @staticmethod
    def _metric_expressions(metrics: Sequence[Metric]) -> list[pl.Expr]:
        expressions: dict[Metric, pl.Expr] = {
            "sessions": pl.len().alias("sessions"),
            "total_seconds": pl.sum("duration_seconds").alias("total_seconds"),
            "average_seconds": pl.mean("duration_seconds").alias("average_seconds"),
            "median_seconds": pl.median("duration_seconds").alias("median_seconds"),
            "minimum_seconds": pl.min("duration_seconds").alias("minimum_seconds"),
            "maximum_seconds": pl.max("duration_seconds").alias("maximum_seconds"),
        }

        return [expressions[metric] for metric in metrics]

    @staticmethod
    def _empty_column_dtype(df: pl.DataFrame, column: str) -> pl.DataType:
        dtype = df.schema[column]

        if dtype == pl.Null:
            return pl.Utf8 #type: ignore

        return dtype

    @staticmethod
    def _metric_dtype(metric: Metric) -> pl.DataType:
        if metric == "sessions":
            return pl.UInt32 #type: ignore

        if metric in {"average_seconds", "median_seconds"}:
            return pl.Float64 #type: ignore

        return pl.Int64 #type: ignore
