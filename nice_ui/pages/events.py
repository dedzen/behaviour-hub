from __future__ import annotations

from datetime import datetime

from nicegui import ui

from timeline.api.timeline import Timeline
from timeline.domain.interval_builder import IntervalBuilder
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Event
from timeline.storage.repository import SQLiteRepository


def parse_event_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("Timestamp must be ISO format") from exc


def event_matches_search(event: Event, search: str) -> bool:
    needle = search.strip().lower()
    if not needle:
        return True

    haystack = [
        str(event.id or ""),
        event.timestamp.isoformat(sep=" "),
        event.device_source.value,
        event.event_kind.value,
        event.category or "",
        event.name or "",
    ]
    return any(needle in value.lower() for value in haystack)


def rebuild_chunks_for_repo(repo: SQLiteRepository) -> list[str]:
    repo.deduplicate_events()
    events = repo.load_events()
    chunks, warnings = IntervalBuilder.build(events)
    repo.replace_chunks(chunks)
    repo.commit()
    return warnings


class EventEditor:
    def __init__(self, on_change=None):
        self.timeline: Timeline | None = None
        self.selected_event: Event | None = None
        self.on_change = on_change

        with ui.dialog() as self.dialog, ui.card().classes("w-[32rem] max-w-full"):
            ui.label("Edit Event").classes("text-h6")
            self.timestamp = ui.input("Timestamp").classes("w-full")
            self.source = ui.select(
                [source.value for source in DeviceSource],
                label="Source",
            ).classes("w-full")
            self.kind = ui.select(
                [kind.value for kind in EventKind],
                label="Kind",
            ).classes("w-full")
            self.category = ui.input("Category").classes("w-full")
            self.name = ui.input("Name").classes("w-full")

            with ui.row().classes("w-full justify-between"):
                ui.button("Delete", on_click=self._delete).props("color=negative")
                with ui.row():
                    ui.button("Cancel", on_click=self.dialog.close).props("flat")
                    ui.button("Save", on_click=self._save)

    def bind(self, timeline: Timeline):
        self.timeline = timeline

    def open(self, timeline: Timeline, event_id: int | None):
        self.bind(timeline)
        if event_id is None:
            ui.notify("Event not found", type="warning")
            return

        selected = timeline.repo.get(Event, event_id)
        if selected is None:
            ui.notify("Event not found", type="warning")
            return

        self.selected_event = selected
        self.timestamp.set_value(str(selected.timestamp))
        self.source.set_value(selected.device_source.value)
        self.kind.set_value(selected.event_kind.value)
        self.category.set_value(selected.category or "")
        self.name.set_value(selected.name or "")
        self.dialog.open()

    def _save(self):
        if self.selected_event is None or self.timeline is None:
            return

        try:
            self.selected_event.timestamp = parse_event_timestamp(self.timestamp.value)
            self.selected_event.device_source = DeviceSource(self.source.value)
            self.selected_event.event_kind = EventKind(self.kind.value)
        except ValueError:
            ui.notify("Timestamp, source, or kind is invalid", type="negative")
            return

        self.selected_event.category = self.category.value or None
        self.selected_event.name = self.name.value or None

        self.timeline.repo.update(self.selected_event)
        self.timeline.repo.commit()
        warnings = rebuild_chunks_for_repo(self.timeline.repo)
        self.dialog.close()
        if self.on_change is not None:
            self.on_change()
        notify_event_change("Event updated", warnings)

    def _delete(self):
        if self.selected_event is None or self.selected_event.id is None or self.timeline is None:
            return

        self.timeline.repo.delete(Event, self.selected_event.id)
        self.timeline.repo.commit()
        warnings = rebuild_chunks_for_repo(self.timeline.repo)
        self.dialog.close()
        self.selected_event = None
        if self.on_change is not None:
            self.on_change()
        notify_event_change("Event deleted", warnings)


def notify_event_change(message: str, warnings: list[str]):
    if warnings:
        ui.notify(
            f"{message}; chunks rebuilt with {len(warnings)} warnings",
            type="warning",
        )
        return

    ui.notify(f"{message}; chunks rebuilt")


class EventsView:
    def __init__(self):
        self.timeline: Timeline | None = None
        self.search_term = ""
        self.events: list[Event] = []

        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Events").classes("text-h6")
                self.count = ui.label("0 events").classes("text-caption text-grey-7")
            self.search = ui.input(
                "Search events",
                placeholder="Timestamp, source, kind, category, name...",
                on_change=self._search_changed,
            ).props("clearable").classes("w-full")
            self.table = ui.table(
                columns=[
                    {"name": "id", "label": "ID", "field": "id"},
                    {"name": "timestamp", "label": "Timestamp", "field": "timestamp"},
                    {"name": "source", "label": "Source", "field": "source"},
                    {"name": "kind", "label": "Kind", "field": "kind"},
                    {"name": "category", "label": "Category", "field": "category"},
                    {"name": "name", "label": "Name", "field": "name"},
                ],
                rows=[],
                row_key="id",
                pagination={"rowsPerPage": 25, "sortBy": "timestamp", "descending": True},
            ).classes("w-full")
            self.table.on("rowClick", self._row_clicked)

        self.editor = EventEditor(on_change=self._editor_changed)

    def update(self, timeline: Timeline):
        self.timeline = timeline
        self.events = timeline.events()
        self._render_rows()

    def _render_rows(self):
        visible_events = [
            event for event in self.events
            if event_matches_search(event, self.search_term)
        ]
        self.table.rows = [self._event_row(event) for event in visible_events]
        self.count.set_text(f"{len(visible_events)} of {len(self.events)} events")
        self.table.update()

    def _search_changed(self, event):
        self.search_term = event.value or ""
        self._render_rows()

    def _row_clicked(self, event):
        row = event.args[1] if len(event.args) > 1 else None
        if not row or self.timeline is None:
            return

        event_id = row.get("id")
        self.editor.open(self.timeline, event_id)

    def _editor_changed(self):
        if self.timeline is not None:
            self.update(self.timeline)

    @staticmethod
    def _event_row(event: Event) -> dict:
        return {
            "id": event.id,
            "timestamp": event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "source": event.device_source.value,
            "kind": event.event_kind.value,
            "category": event.category or "",
            "name": event.name or "",
        }
