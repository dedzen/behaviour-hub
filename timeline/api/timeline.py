from __future__ import annotations
from collections.abc import Iterable

from datetime import date, datetime, time, timedelta
from dataclasses import dataclass, replace, asdict
import polars as pl

from timeline.api.query import Query
from timeline.storage.repository import SQLiteRepository
from timeline.domain.enums import DeviceSource
from timeline.domain.models import *
from timeline.statistics.suite import StatisticsSuite
from timeline.statistics.chunk_stats import ChunkStatistics
from timeline.analytics.suite import AnalyticsSuite
from timeline.api.metadata import Metadata 


def parse_db_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class Timeline:
    repo: SQLiteRepository
    query: Query = Query()
    

    def _replace_query(self, **kwargs) -> "Timeline":
            return replace(
                self,
                query=replace(self.query, **kwargs),
            )

    def day(self, day: date | str) -> Timeline:
        day = self._parse_day(day)

        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)

        return self._replace_query(
            start=start,
            end=end,
        )

    def week(
        self,
        week: tuple[int, int] | str,
    ) -> Timeline:

        year, week = self._parse_week(week) #type: ignore

        start_date = date.fromisocalendar(year, week, 1) #type: ignore

        start = datetime.combine(start_date, time.min)
        end = start + timedelta(days=7)

        return self._replace_query(
            start=start,
            end=end,
        )

    def month(
        self,
        month: tuple[int, int] | str,
    ) -> Timeline:
        year, month = self._parse_month(month) #type: ignore
        start = datetime(year, month, 1) #type: ignore
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1) #type: ignore
        return self._replace_query(
            start=start,
            end=end,
        )

    def year(
        self,
        year: int | str,
    ) -> Timeline:

        year = self._parse_year(year)

        return self._replace_query(
            start=datetime(year, 1, 1),
            end=datetime(year + 1, 1, 1),
        )

    def last(
        self,
        *,
        days: int,
    ) -> Timeline:

        end = datetime.now()
        start = end - timedelta(days=days)

        return self._replace_query(
            start=start,
            end=end,
        )

    def category(self, category: str | Iterable[str]) -> "Timeline":
        if isinstance(category, str):
            category = {category}
        else:
            category = set(category)
        return self._replace_query(
            categories = frozenset(category)
        )

    def activity(self, activity: str | Iterable[str]) -> "Timeline":
        if isinstance(activity, str):
            activity = {activity}
        else:
            activity = set(activity)

        return self._replace_query(
            activities=frozenset(activity),
        )

    def source(self, source: DeviceSource | Iterable[DeviceSource]) -> "Timeline":
        if isinstance(source, DeviceSource):
            source = {source}
        else:
            activity = set(source)
        return self._replace_query(
            sources=frozenset(source),
        )

    def between(self, start, end) -> "Timeline":
        return self._replace_query(start=start, end=end)   
    def before(self, end) -> "Timeline":
            return self._replace_query(end=end)     
    def after(self, start) -> "Timeline":
            return self._replace_query(start=start)    

    def duration(
        self,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> Timeline:
        """Filter by duration in seconds."""

        return self._replace_query(
            min_duration=minimum,
            max_duration=maximum,
        )

    def min_duration(
        self,
        seconds: int,
    ) -> Timeline:
        """Keep sessions at least this long."""

        return self._replace_query(
            min_duration=seconds,
        )

    def max_duration(
        self,
        seconds: int,
    ) -> Timeline:
        """Keep sessions at most this long."""

        return self._replace_query(
            max_duration=seconds,
        )

    def weekday(
        self,
        weekday: int,
    ) -> Timeline:
        """Filter by weekday (Monday=0 ... Sunday=6)."""

        if not 0 <= weekday <= 6:
            raise ValueError("weekday must be between 0 and 6")

        return self._replace_query(
            weekday=weekday,
        )


    def events(self) -> list[Event]:
        """Return events matching this view."""
        return self.repo.load_events(self.query)
    def chunks(self) -> list[Chunk]:
        """Return interval chunks matching this view."""
        return self.repo.load_chunks(self.query)

    def points(self) -> list[Point]:
        """Return point events matching this view."""
        return self.repo.load_points(self.query)

    def annotations(self) -> list[Annotation]:
        """Return annotations matching this view."""
        return self.repo.load_annotations(self.query)

    def context(self) -> list[Context]:
        """Return context entries matching this view."""
        return self.repo.load_context(self.query)

    def day_marker(self, day: date | str) -> DayMarker | None:
        return self.repo.get_day_marker(self._parse_day(day))

    def save_day_marker(self, marker: DayMarker) -> DayMarker:
        return self.repo.upsert_day_marker(marker)

    def day_picture(self, day: date | str) -> DayPicture:
        from timeline.analytics.screen_time_intersection import active_screen_intersection

        selected_day = self._parse_day(day)
        day_timeline = Timeline(self.repo, Query()).day(selected_day)
        activity_df = day_timeline.source(DeviceSource.EMBED).to_clipped_polars()
        activity_names = (
            activity_df["name"].drop_nulls().unique().to_list()
            if not activity_df.is_empty()
            else []
        )
        screen_df = (
            day_timeline
            .source(DeviceSource.PHONE)
            .category("Screen")
            .activity("Screen on")
            .to_clipped_polars()
        )

        return DayPicture(
            day=selected_day,
            marker=self.day_marker(selected_day),
            tracked_seconds=self._sum_seconds(activity_df),
            active_screen_seconds=self._sum_seconds(screen_df),
            sleep_seconds=self._activity_seconds(activity_df, "Sleep"),
            top_activity=self._top_activity(activity_df, exclusions={"sleep"}),
            activity_summary=ChunkStatistics(activity_df).by_activity(),
            screen_intersection=active_screen_intersection(day_timeline, activity_names),
        )

    def __iter__(self):
        return iter(self.chunks())

    def to_polars(self) -> pl.DataFrame:
        sql, params = self.repo._select_sql(
            "chunks",
            timestamp_column="start_timestamp",
            query=self.query,
        )

        df =  pl.read_database(
            query=sql,
            connection=self.repo.conn,
            execute_options={"parameters": params},
        )
        return self._normalize_chunk_dataframe(df)

    def to_clipped_polars(self) -> pl.DataFrame:
        sql, params = self._overlapping_chunks_sql()

        df = pl.read_database(
            query=sql,
            connection=self.repo.conn,
            execute_options={"parameters": params},
        )

        df = self._normalize_chunk_dataframe(df)

        if df.is_empty():
            return df

        expressions = []
        query_start = self._query_datetime(self.query.start)
        query_end = self._query_datetime(self.query.end)

        if query_start is not None:
            expressions.append(
                pl.max_horizontal(
                    pl.col("start_timestamp"),
                    pl.lit(query_start),
                ).alias("start_timestamp")
            )

        if query_end is not None:
            expressions.append(
                pl.min_horizontal(
                    pl.col("end_timestamp"),
                    pl.lit(query_end),
                ).alias("end_timestamp")
            )

        if expressions:
            df = df.with_columns(expressions)

        df = df.with_columns(
            (
                (pl.col("end_timestamp") - pl.col("start_timestamp"))
                .dt.total_seconds()
                .cast(pl.Int64)
            ).alias("duration_seconds")
        )

        if self.query.min_duration is not None:
            df = df.filter(pl.col("duration_seconds") >= self.query.min_duration)

        if self.query.max_duration is not None:
            df = df.filter(pl.col("duration_seconds") <= self.query.max_duration)

        return df.filter(pl.col("duration_seconds") >= 0)

    def _overlapping_chunks_sql(self) -> tuple[str, list]:
        where: list[str] = []
        params: list = []
        query_start = self._query_datetime(self.query.start)
        query_end = self._query_datetime(self.query.end)

        if query_start is not None:
            where.append("end_timestamp > ?")
            params.append(query_start.isoformat(sep=" "))

        if query_end is not None:
            where.append("start_timestamp < ?")
            params.append(query_end.isoformat(sep=" "))

        self.query._where_in(where, params, "category", self.query.categories)
        self.query._where_in(where, params, "name", self.query.activities)
        self.query._where_in(
            where,
            params,
            "source",
            self.query.sources,
            transform=lambda source: source.value,
        )

        if self.query.weekday is not None:
            where.append("CAST(strftime('%w', start_timestamp) AS INTEGER) = ?")
            params.append(self.query.weekday)

        if self.query.search is not None:
            where.append("(name LIKE ? OR category LIKE ?)")
            pattern = f"%{self.query.search}%"
            params.extend([pattern, pattern])

        where_sql = ""
        if where:
            where_sql = "WHERE " + " AND ".join(where)

        return (
            f"""
            SELECT *
            FROM chunks
            {where_sql}
            ORDER BY start_timestamp
            """,
            params,
        )

    @staticmethod
    def _query_datetime(value: date | datetime | None) -> datetime | None:
        if value is None:
            return None

        if isinstance(value, datetime):
            return value

        return datetime.combine(value, time.min)

    @staticmethod
    def _normalize_chunk_dataframe(df: pl.DataFrame) -> pl.DataFrame:
        columns = {
            "id": pl.Int64,
            "start_timestamp": pl.Datetime,
            "end_timestamp": pl.Datetime,
            "duration_seconds": pl.Int64,
            "category": pl.Utf8,
            "name": pl.Utf8,
            "source": pl.Utf8,
            "start_event_id": pl.Int64,
            "end_event_id": pl.Int64,
        }

        if df.is_empty() and not df.columns:
            return pl.DataFrame(schema=columns)

        return df.with_columns(
            pl.col("start_timestamp")
            .cast(pl.Utf8)
            .map_elements(parse_db_datetime, return_dtype=pl.Datetime),
            pl.col("end_timestamp")
            .cast(pl.Utf8)
            .map_elements(parse_db_datetime, return_dtype=pl.Datetime),
        )

    @staticmethod
    def _sum_seconds(df: pl.DataFrame) -> int:
        if df.is_empty():
            return 0
        return int(df.select(pl.sum("duration_seconds")).item() or 0)

    @staticmethod
    def _activity_seconds(df: pl.DataFrame, activity: str) -> int:
        if df.is_empty():
            return 0

        value = (
            df
            .filter(pl.col("name").str.to_lowercase() == activity.lower())
            .select(pl.sum("duration_seconds"))
            .item()
        )
        return int(value or 0)

    @staticmethod
    def _top_activity(df: pl.DataFrame, *, exclusions: set[str]) -> str | None:
        if df.is_empty():
            return None

        top = (
            df
            .filter(~pl.col("name").str.to_lowercase().is_in(exclusions))
            .group_by("name")
            .agg(pl.sum("duration_seconds").alias("total_seconds"))
            .sort("total_seconds", descending=True)
            .head(1)
        )

        if top.is_empty():
            return None

        return top.to_dicts()[0]["name"]

    @property
    def statistics(self):
        return StatisticsSuite(self)    
    @property
    def analytics(self):
        return AnalyticsSuite(self)
    @property
    def metadata(self):
        return Metadata(self.repo, self.query)

    @staticmethod
    def _parse_day(day: date | str) -> date:
        if isinstance(day, date):
            return day

        return date.fromisoformat(day)

    @staticmethod
    def _parse_week(week: tuple[int, int] | str) -> tuple[int, int]:
        if isinstance(week, tuple):
            return week

        year, week = week.split("-")
        return int(year), int(week)

    @staticmethod
    def _parse_month(month: tuple[int, int] | str) -> tuple[int, int]:
        if isinstance(month, tuple):
            return month

        year, month = month.split("-")
        return int(year), int(month)

    @staticmethod
    def _parse_year(year: int | str) -> int:
        return int(year)
