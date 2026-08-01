from __future__ import annotations

from collections.abc import Iterable

from timeline.domain.models import Event, Chunk
from timeline.domain.enums import DeviceSource, EventKind


class IntervalBuilder:
    """
    Builds time intervals (chunks) from a stream of Events.

    Each device source has its own interval state. Intervals from different
    sources may overlap, but a single source may only have one active interval.

    Usage:

        builder = IntervalBuilder()

        for event in events:
            builder.add(event)

        chunks = builder.finish()
    """

    def __init__(self):
        self._active: dict[DeviceSource, Event] = {}

        self._chunks: list[Chunk] = []
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return self._warnings

    @property
    def chunks(self) -> list[Chunk]:
        return self._chunks

    def _describe(self, event: Event) -> str:
        return (
            f"{event.device_source.value}/"
            f"{event.category or '<missing>'}/"
            f"{event.name or '<missing>'}"
        )

    def add(self, event: Event) -> None:

        # Points do not create intervals
        if event.event_kind == EventKind.POINT:
            return

        source = event.device_source

        # ------------------------
        # START
        # ------------------------

        if event.event_kind == EventKind.INTERVAL_START:

            if source in self._active:
                current = self._active[source]

                self._warnings.append(
                    f"Duplicate start on {source.value}: "
                    f"{self._describe(event)} at {event.timestamp} "
                    f"while {self._describe(current)} is active"
                )
                return

            self._active[source] = event
            return

        # ------------------------
        # END
        # ------------------------

        if event.event_kind == EventKind.INTERVAL_END:

            start = self._active.get(source)

            if start is None:

                self._warnings.append(
                    f"End without start: {self._describe(event)} "
                    f"at {event.timestamp}"
                )

                return

            if event.category != start.category or event.name != start.name:
                self._warnings.append(
                    f"End does not match active start on {source.value}: "
                    f"started {self._describe(start)} at {start.timestamp}, "
                    f"ended {self._describe(event)} at {event.timestamp}"
                )
                return

            duration = int(
                (event.timestamp - start.timestamp).total_seconds()
            )

            if duration < 0:

                self._warnings.append(
                    f"Negative duration: {self._describe(event)}"
                )

                return

            self._active.pop(source, None)

            self._chunks.append(
                Chunk(
                    start_timestamp=start.timestamp,
                    end_timestamp=event.timestamp,
                    duration_seconds=duration,
                    category=start.category,
                    name=start.name,
                    source=start.device_source,
                    start_event_id=start.id, # type: ignore
                    end_event_id=event.id, # type: ignore
                )
            )

    def finish(self) -> list[Chunk]:

        # Report unfinished intervals
        for event in self._active.values():

            self._warnings.append(
                f"Unclosed interval: {self._describe(event)} "
                f"(started {event.timestamp})"
            )

        self._active.clear()

        return self._chunks

    @classmethod
    def build(cls, events: Iterable[Event]) -> tuple[list[Chunk], list[str]]:
        """
        Convenience method.
        """

        builder = cls()

        for event in events:
            builder.add(event)

        chunks = builder.finish()

        return chunks, builder.warnings
