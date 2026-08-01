from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from timeline.api.timeline import Timeline


from .chunk_stats import ChunkStatistics

class StatisticsSuite:
    def __init__(self, timeline: Timeline) -> None:
        self.timeline = timeline
    @property
    def chunks(self):
        return ChunkStatistics(self.timeline.to_polars())