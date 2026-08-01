from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from timeline.domain.models import Event
from timeline.domain.enums import DeviceSource, EventKind


EVENT_KIND_MAP = {
    "start": EventKind.INTERVAL_START,
    "end": EventKind.INTERVAL_END,
    "point": EventKind.POINT,
}


def split_task(task: str) -> tuple[str | None, str]:
    """
    Examples

    'Street: Walking'
        -> ('Street', 'Walking')

    'Sleep'
        -> (None, 'Sleep')
    """

    if ":" not in task:
        return None, task.strip()

    category, name = task.split(":", 1)

    return category.strip(), name.strip()


def import_embed_csv(filename: Path) -> list[Event]:

    events: list[Event] = []

    with open(filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for line_number, row in enumerate(reader, start=2):
            try:
                timestamp = datetime.fromisoformat(row["timestamp"])

                event_kind = EVENT_KIND_MAP[row["event"]]

                category, name = split_task(row["task"])

                events.append(
                    Event(
                        timestamp=timestamp,
                        device_source=DeviceSource.EMBED,
                        event_kind=event_kind,
                        category=category,
                        name=name,
                    )
                )

            except Exception as e:
                raise ValueError(f"Error on line {line_number}: {e}") from e

    return events
