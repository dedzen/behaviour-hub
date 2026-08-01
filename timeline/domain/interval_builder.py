from __future__ import annotations

from collections.abc import Iterable

from timeline.domain.models import Event, Chunk
from timeline.domain.enums import EventKind


class IntervalBuilder:
    """
    Builds time intervals (chunks) from a stream of Events.

    Usage:

        builder = IntervalBuilder()

        for event in events:
            builder.add(event)

        chunks = builder.finish()
    """

    def __init__(self):
        self._active: dict[tuple[str, str | None, str | None], Event] = {}

        self._chunks: list[Chunk] = []
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return self._warnings

    @property
    def chunks(self) -> list[Chunk]:
        return self._chunks

    def _key(self, event: Event) -> tuple[str, str | None, str | None]:
        return (
            event.device_source,
            event.category,
            event.name,
        )

    def add(self, event: Event) -> None:

        # Points do not create intervals
        if event.event_kind == EventKind.POINT:
            return

        key = self._key(event)

        # ------------------------
        # START
        # ------------------------

        if event.event_kind == EventKind.INTERVAL_START:

            if key in self._active:

                self._warnings.append(
                    f"Duplicate start: {key} "
                    f"at {event.timestamp}"
                )

            self._active[key] = event
            return

        # ------------------------
        # END
        # ------------------------

        if event.event_kind == EventKind.INTERVAL_END:

            start = self._active.pop(key, None)

            if start is None:

                self._warnings.append(
                    f"End without start: {key} "
                    f"at {event.timestamp}"
                )

                return

            duration = int(
                (event.timestamp - start.timestamp).total_seconds()
            )

            if duration < 0:

                self._warnings.append(
                    f"Negative duration: {key}"
                )

                return

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
        for key, event in self._active.items():

            self._warnings.append(
                f"Unclosed interval: {key} "
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