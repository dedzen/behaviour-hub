from __future__ import annotations
from typing import Any, ClassVar
from dataclasses import dataclass
from datetime import date, datetime
import json
from sqlite3 import Row
from timeline.domain.enums import DeviceSource, EventKind

@dataclass(slots=True)
class Event:
    timestamp: datetime

    device_source: DeviceSource
    event_kind: EventKind

    category: str | None
    name: str | None

    id: int | None = None

    @classmethod
    def from_row(cls, row: Row) -> "Event":
        return cls(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            device_source=DeviceSource(row["device_source"]),
            event_kind=EventKind(row["event_kind"]),
            category=row["category"],
            name=row["name"],
        )

    def to_db_tuple(self) -> tuple:
        """
        Returns the values in the same order expected by
        INSERT INTO events(...).
        """
        return (
            self.timestamp.isoformat(sep=" "),
            self.device_source.value,
            self.event_kind.value,
            self.category,
            self.name,
        )
    
    TABLE: ClassVar[str] = "events"

    UPDATE_SQL: ClassVar[str] = """
    UPDATE events
    SET
        timestamp = ?,
        device_source = ?,
        event_kind = ?,
        category = ?,
        name = ?
    WHERE id = ?
    """


@dataclass(slots=True)
class Chunk:
    start_timestamp: datetime
    end_timestamp: datetime

    duration_seconds: int

    category: str | None
    name: str | None

    source: DeviceSource

    start_event_id: int
    end_event_id: int

    id: int | None = None

    @classmethod
    def from_row(cls, row: Row) -> "Chunk":
        return cls(
            id=row["id"],
            start_timestamp=datetime.fromisoformat(row["start_timestamp"]),
            end_timestamp=datetime.fromisoformat(row["end_timestamp"]),
            duration_seconds=row["duration_seconds"],
            category=row["category"],
            name=row["name"],
            source=DeviceSource(row["source"]),
            start_event_id=row["start_event_id"],
            end_event_id=row["end_event_id"],
        )
    
    def to_db_tuple(self) -> tuple:
        """
        Returns the values in the order expected by
        INSERT INTO chunks(...).
        """
        return (
            self.start_timestamp.isoformat(sep=" "),
            self.end_timestamp.isoformat(sep=" "),
            self.duration_seconds,
            self.source.value,
            self.category,
            self.name,
            self.start_event_id,
            self.end_event_id,
        )

    TABLE: ClassVar[str] = "chunks"

    UPDATE_SQL: ClassVar[str] = """
    UPDATE chunks
    SET
        start_timestamp = ?,
        end_timestamp = ?,
        duration_seconds = ?,
        source = ?,
        category = ?,
        name = ?,
        start_event_id = ?,
        end_event_id = ?
    WHERE id = ?
    """

@dataclass(slots=True)
class Point:
    timestamp: datetime

    category: str | None
    name: str

    source: DeviceSource

    event_id: int | None = None

    id: int | None = None

    @classmethod
    def from_row(cls, row: Row) -> "Point":
        return cls(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            category=row["category"],
            name=row["name"],
            source=DeviceSource(row["source"]),
            event_id=row["event_id"],
        )

    def to_db_tuple(self) -> tuple:
        return (
            self.timestamp.isoformat(sep=" "),
            self.category,
            self.name,
            self.source.value,
            self.event_id,
        )

    TABLE: ClassVar[str] = "points"

    UPDATE_SQL: ClassVar[str] = """
    UPDATE points
    SET
        timestamp = ?,
        category = ?,
        name = ?,
        source = ?,
        event_id = ?
    WHERE id = ?
    """
    
@dataclass(slots=True)
class Annotation:
    timestamp: datetime

    text: str

    chunk_id: int | None = None
    point_id: int | None = None

    id: int | None = None

    @classmethod
    def from_row(cls, row: Row) -> "Annotation":
        return cls(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            text=row["text"],
            chunk_id=row["chunk_id"],
            point_id=row["point_id"],
        )

    def to_db_tuple(self) -> tuple:
        return (
            self.timestamp.isoformat(sep=" "),
            self.text,
            self.chunk_id,
            self.point_id,
        )
    TABLE: ClassVar[str] = "annotations"

    UPDATE_SQL: ClassVar[str] = """
    UPDATE annotations
    SET
        timestamp = ?,
        text = ?,
        chunk_id = ?,
        point_id = ?
    WHERE id = ?
    """
    
@dataclass(slots=True)
class Context:
    timestamp: datetime

    key: str
    value: str

    source: DeviceSource

    id: int | None = None

    @classmethod
    def from_row(cls, row: Row) -> "Context":
        return cls(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            key=row["key"],
            value=row["value"],
            source=DeviceSource(row["source"]),
        )

    def to_db_tuple(self) -> tuple:
        return (
            self.timestamp.isoformat(sep=" "),
            self.key,
            self.value,
            self.source.value,
        )

    TABLE: ClassVar[str] = "context"

    UPDATE_SQL: ClassVar[str] = """
    UPDATE context
    SET
        timestamp = ?,
        key = ?,
        value = ?,
        source = ?
    WHERE id = ?
    """


@dataclass(slots=True)
class DayMarker:
    day: date
    habits: dict[str, bool]
    people: list[str]
    quick_note_markdown: str
    mood: float | None

    id: int | None = None

    @classmethod
    def from_row(cls, row: Row) -> "DayMarker":
        return cls(
            id=row["id"],
            day=date.fromisoformat(row["day"]),
            habits=json.loads(row["habits_json"] or "{}"),
            people=json.loads(row["people_json"] or "[]"),
            quick_note_markdown=row["quick_note_markdown"] or "",
            mood=row["mood"],
        )

    def to_db_tuple(self) -> tuple:
        return (
            self.day.isoformat(),
            json.dumps(self.habits, sort_keys=True),
            json.dumps(self.people),
            self.quick_note_markdown,
            self.mood,
        )

    TABLE: ClassVar[str] = "day_markers"

    UPDATE_SQL: ClassVar[str] = """
    UPDATE day_markers
    SET
        day = ?,
        habits_json = ?,
        people_json = ?,
        quick_note_markdown = ?,
        mood = ?
    WHERE id = ?
    """


@dataclass(slots=True)
class DayPicture:
    day: date
    marker: DayMarker | None
    tracked_seconds: int
    active_screen_seconds: int
    sleep_seconds: int
    top_activity: str | None
    activity_summary: Any
    screen_intersection: Any
