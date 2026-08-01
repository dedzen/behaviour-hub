from __future__ import annotations
from datetime import date, datetime

from timeline.storage.repository import SQLiteRepository
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from timeline.api.timeline import Timeline
    from timeline.api.query import Query

class Metadata:

    def __init__(
        self,
        repository: SQLiteRepository,
        query: Query,
    ):
        self.repository = repository
        self.query = query
    @property
    def activities(self) -> list[str]:
        return self.repository.distinct(
            "chunks",
            "name",
            query=self.query,
        )
    @property
    def categories(self) -> list[str]:
        return self.repository.distinct(
            "chunks",
            "category",
            query=self.query,
        )
    @property
    def devices(self) -> list[str]:
        return self.repository.distinct(
            "chunks",
            "source",
            query=self.query,
        )
    @property
    def date_range(self) -> tuple[datetime | None, datetime | None]:
        return self.repository.date_range(
            "chunks",
            query=self.query,
        )
    @property
    def activity_tree(self) -> dict[str, list[str]]:
        return self.repository.activity_tree(
            query=self.query,
        )
    @property
    def activities_by_category(self) -> list[tuple[str, str]]:
        tree = self.activity_tree

        return [
            (category, activity)
            for category, activities in tree.items()
            for activity in activities
        ]