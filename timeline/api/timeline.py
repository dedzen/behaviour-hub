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
from timeline.analytics.suite import AnalyticsSuite
from timeline.api.metadata import Metadata 

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
        return df.with_columns(
        pl.col("start_timestamp").cast(pl.Utf8).str.to_datetime(),
        pl.col("end_timestamp").cast(pl.Utf8).str.to_datetime(),
        )

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
