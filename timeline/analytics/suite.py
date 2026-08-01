from __future__ import annotations
from typing import TYPE_CHECKING

from .chunk_analytics import ChunkAnalytics

if TYPE_CHECKING:
    from timeline.api.timeline import Timeline


class AnalyticsSuite:
    def __init__(self, timeline: Timeline) -> None:
        self.timeline = timeline

    @property
    def chunks(self):
        return ChunkAnalytics(self.timeline.to_polars())
