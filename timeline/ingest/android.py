from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Event

AndroidStrategy = Literal["screen", "keyguard"]

SCREEN_EVENT_MAP = {
    "SCREEN_INTERACTIVE": EventKind.INTERVAL_START,
    "SCREEN_NON_INTERACTIVE": EventKind.INTERVAL_END,
}
KEYGUARD_EVENT_MAP = {
    "KEYGUARD_HIDDEN": EventKind.INTERVAL_START,
    "KEYGUARD_SHOWN": EventKind.INTERVAL_END,
}


@dataclass(frozen=True, slots=True)
class AndroidImportResult:
    events: list[Event]
    ignored_events: int
    dropped_orphan_starts: int
    strategy: AndroidStrategy


def parse_android_timestamp(value: str) -> datetime:
    # The app records local wall-clock time with an offset. Behaviour Hub uses
    # naive local datetimes internally, so we preserve the local clock reading.
    return datetime.fromisoformat(value).replace(tzinfo=None)


def import_android_unlock_jsonl(
    filename: Path,
    *,
    strategy: AndroidStrategy = "keyguard",
) -> AndroidImportResult:
    event_map = {
        "screen": SCREEN_EVENT_MAP,
        "keyguard": KEYGUARD_EVENT_MAP,
    }[strategy]

    events: list[Event] = []
    ignored_events = 0
    dropped_orphan_starts = 0
    open_start_index: int | None = None

    with filename.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                row = json.loads(line)
                event_name = row["event"]
                event_kind = event_map.get(event_name)

                if event_kind is None:
                    ignored_events += 1
                    continue

                event = Event(
                    timestamp=parse_android_timestamp(row["timestamp"]),
                    device_source=DeviceSource.PHONE,
                    event_kind=event_kind,
                    category="Screen",
                    name="Screen on",
                )

                if event.event_kind == EventKind.INTERVAL_START:
                    if open_start_index is not None:
                        events[open_start_index] = event
                        dropped_orphan_starts += 1
                    else:
                        events.append(event)
                        open_start_index = len(events) - 1
                    continue

                events.append(event)
                open_start_index = None
            except Exception as exc:
                raise ValueError(f"Error on line {line_number}: {exc}") from exc

    return AndroidImportResult(
        events=events,
        ignored_events=ignored_events,
        dropped_orphan_starts=dropped_orphan_starts,
        strategy=strategy,
    )
