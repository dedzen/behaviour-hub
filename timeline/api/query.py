from datetime import datetime, date
from collections.abc import Collection
from dataclasses import dataclass, replace, field
from timeline.domain.enums import DeviceSource


@dataclass(frozen=True, slots=True)
class Query:
    start: datetime | None = None
    end: datetime | None = None

    categories: frozenset[str] = field(default_factory=frozenset)
    activities: frozenset[str] = field(default_factory=frozenset)
    sources: frozenset[DeviceSource] = field(default_factory=frozenset)
    min_duration: int | None = None
    max_duration: int | None = None

    weekday: int | None = None

    search: str | None = None

    @staticmethod
    def _where_in(
        where: list[str],
        params: list,
        column: str,
        values: Collection,
        *,
        transform=lambda x: x,
    ) -> None:
        if not values:
            return

        placeholders = ",".join("?" for _ in values)

        where.append(f"{column} IN ({placeholders})")
        params.extend(transform(v) for v in sorted(values))

    def where_clause(
        self,
        *,
        timestamp_column: str = "timestamp",
    ) -> tuple[str, list]:

        where: list[str] = []
        params: list = []

        if self.start is not None:
            where.append(f"{timestamp_column} >= ?")
            if isinstance(self.start, date):
                params.append(
                    datetime.combine(self.start, datetime.min.time()).isoformat(sep=" ")
                )
            else:
                params.append(self.start.isoformat(sep=" "))

        if self.end is not None:
            where.append(f"{timestamp_column} <= ?")
            if isinstance(self.end, date):
                params.append(
                    datetime.combine(self.end, datetime.min.time()).isoformat(sep=" ")
                )
            else:
                params.append(self.end.isoformat(sep=" "))

        self._where_in(
            where,
            params,
            "category",
            self.categories,
        )

        self._where_in(
            where,
            params,
            "name",
            self.activities,
        )

        self._where_in(
            where,
            params,
            "source",
            self.sources,
            transform=lambda s: s.value,
        )

        if self.min_duration is not None:
            where.append("duration_seconds >= ?")
            params.append(self.min_duration)

        if self.max_duration is not None:
            where.append("duration_seconds <= ?")
            params.append(self.max_duration)

        if self.weekday is not None:
            where.append(f"CAST(strftime('%w', {timestamp_column}) AS INTEGER) = ?")
            params.append(self.weekday)

        if self.search is not None:
            where.append("(name LIKE ? OR category LIKE ?)")
            pattern = f"%{self.search}%"
            params.extend([pattern, pattern])

        if not where:
            return "", params
        return (
            "WHERE " + " AND ".join(where),
            params,
        )
