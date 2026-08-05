from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Event

AndroidStrategy = Literal["active_screen", "screen", "keyguard"]

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
    anomalies: tuple[str, ...] = ()
    unknown_time_seconds: float = 0.0
    dropped_short_chunks: int = 0


@dataclass(slots=True)
class _PhoneState:
    screen_interactive: bool | None = None
    keyguard_hidden: bool | None = None
    shutdown_active: bool = False


def parse_android_timestamp(value: str) -> datetime:
    # The app records local wall-clock time with an offset. Behaviour Hub uses
    # naive local datetimes internally, so we preserve the local clock reading.
    return datetime.fromisoformat(value).replace(tzinfo=None)


def _screen_on_event(timestamp: datetime, event_kind: EventKind) -> Event:
    return Event(
        timestamp=timestamp,
        device_source=DeviceSource.PHONE,
        event_kind=event_kind,
        category="Screen",
        name="Screen on",
    )


def _active_state(state: _PhoneState) -> bool | None:
    if state.shutdown_active:
        return False
    if state.screen_interactive is None or state.keyguard_hidden is None:
        return None
    return state.screen_interactive and state.keyguard_hidden


def _apply_state_event(
    state: _PhoneState,
    event_name: str,
) -> tuple[str | None, bool | None, bool | None]:
    if event_name == "SCREEN_INTERACTIVE":
        before = state.screen_interactive
        state.screen_interactive = True
        return ("repeated_screen_interactive" if before is True else None, before, True)

    if event_name == "SCREEN_NON_INTERACTIVE":
        before = state.screen_interactive
        state.screen_interactive = False
        return ("repeated_screen_non_interactive" if before is False else None, before, False)

    if event_name == "KEYGUARD_HIDDEN":
        before = state.keyguard_hidden
        state.keyguard_hidden = True
        return ("repeated_keyguard_hidden" if before is True else None, before, True)

    if event_name == "KEYGUARD_SHOWN":
        before = state.keyguard_hidden
        state.keyguard_hidden = False
        return ("repeated_keyguard_shown" if before is False else None, before, False)

    if event_name == "DEVICE_SHUTDOWN":
        before = state.shutdown_active
        state.shutdown_active = True
        return ("repeated_device_shutdown" if before is True else None, before, True)

    if event_name == "DEVICE_STARTUP":
        before = state.shutdown_active
        state.shutdown_active = False
        return ("startup_without_shutdown" if before is False else None, before, False)

    return None, None, None


def _drop_short_intervals(events: list[Event], minimum_seconds: int = 20) -> tuple[list[Event], int]:
    filtered: list[Event] = []
    open_start: Event | None = None
    dropped_short_chunks = 0

    for event in events:
        if event.event_kind == EventKind.INTERVAL_START:
            if open_start is not None:
                filtered.append(open_start)
            open_start = event
            continue

        if event.event_kind == EventKind.INTERVAL_END and open_start is not None:
            seconds = (event.timestamp - open_start.timestamp).total_seconds()
            if seconds < minimum_seconds:
                dropped_short_chunks += 1
            else:
                filtered.append(open_start)
                filtered.append(event)
            open_start = None
            continue

        filtered.append(event)

    if open_start is not None:
        filtered.append(open_start)

    return filtered, dropped_short_chunks


def _import_active_screen(rows: list[tuple[int, datetime, str]], ignored_events: int) -> AndroidImportResult:
    state = _PhoneState()
    events: list[Event] = []
    anomalies: list[str] = []
    active_open = False
    active_start_timestamp: datetime | None = None
    unknown_since: datetime | None = rows[0][1] if rows else None
    unknown_time_seconds = 0.0

    for line_number, timestamp, event_name in rows:
        before_active = _active_state(state)
        anomaly, before_value, after_value = _apply_state_event(state, event_name)
        after_active = _active_state(state)

        if anomaly:
            anomalies.append(
                f"line {line_number}: {anomaly} on {event_name} "
                f"({before_value!r} -> {after_value!r})"
            )

        if before_active is None and after_active is not None and unknown_since is not None:
            unknown_time_seconds += max(0.0, (timestamp - unknown_since).total_seconds())
            unknown_since = None
        elif after_active is None and unknown_since is None:
            unknown_since = timestamp

        if before_active is True and after_active is not True and active_open:
            events.append(_screen_on_event(timestamp, EventKind.INTERVAL_END))
            active_open = False
            active_start_timestamp = None
        elif before_active is not True and after_active is True:
            events.append(_screen_on_event(timestamp, EventKind.INTERVAL_START))
            active_open = True
            active_start_timestamp = timestamp

    if active_open and active_start_timestamp is not None and rows:
        range_end = rows[-1][1]
        if active_start_timestamp < range_end:
            events.append(_screen_on_event(range_end, EventKind.INTERVAL_END))
        else:
            events.pop()

    events, dropped_short_chunks = _drop_short_intervals(events)

    return AndroidImportResult(
        events=events,
        ignored_events=ignored_events,
        dropped_orphan_starts=0,
        strategy="active_screen",
        anomalies=tuple(anomalies),
        unknown_time_seconds=unknown_time_seconds,
        dropped_short_chunks=dropped_short_chunks,
    )


def import_android_unlock_jsonl(
    filename: Path,
    *,
    strategy: AndroidStrategy = "active_screen",
) -> AndroidImportResult:
    rows: list[tuple[int, datetime, str]] = []
    ignored_events = 0

    known_active_screen_events = {
        "SCREEN_INTERACTIVE",
        "SCREEN_NON_INTERACTIVE",
        "KEYGUARD_HIDDEN",
        "KEYGUARD_SHOWN",
        "DEVICE_SHUTDOWN",
        "DEVICE_STARTUP",
    }

    with filename.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                row = json.loads(line)
                event_name = row["event"]
                if strategy == "active_screen" and event_name not in known_active_screen_events:
                    ignored_events += 1
                    continue
                rows.append((line_number, parse_android_timestamp(row["timestamp"]), event_name))
            except Exception as exc:
                raise ValueError(f"Error on line {line_number}: {exc}") from exc

    rows.sort(key=lambda row: (row[1], row[0]))

    if strategy == "active_screen":
        return _import_active_screen(rows, ignored_events)

    event_map = {
        "screen": SCREEN_EVENT_MAP,
        "keyguard": KEYGUARD_EVENT_MAP,
    }[strategy]

    events: list[Event] = []
    dropped_orphan_starts = 0
    open_start_index: int | None = None

    for _, timestamp, event_name in rows:
        event_kind = event_map.get(event_name)

        if event_kind is None:
            ignored_events += 1
            continue

        event = _screen_on_event(timestamp, event_kind)

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

    events, dropped_short_chunks = _drop_short_intervals(events)

    return AndroidImportResult(
        events=events,
        ignored_events=ignored_events,
        dropped_orphan_starts=dropped_orphan_starts,
        strategy=strategy,
        dropped_short_chunks=dropped_short_chunks,
    )
