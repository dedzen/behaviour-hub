from __future__ import annotations

from datetime import datetime

from nicegui import ui

from timeline.api.timeline import Timeline
from timeline.domain.interval_builder import IntervalBuilder
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Event
from timeline.storage.repository import SQLiteRepository
from timeline.storage.errors import ConcurrentModificationError
from nice_ui.responsive import visible_columns_expression


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
    def __init__(self, on_change=None, mutation_api=None):
        self.timeline: Timeline | None = None
        self.selected_event: Event | None = None
        self.on_change = on_change
        self.mutation_api = mutation_api
        self.dirty = False
        self.stale = False
        self._loading = False

        with ui.dialog() as self.dialog, ui.card().classes(
            "bh-dialog-panel w-[32rem] max-w-full"
        ):
            ui.label("Edit Event").classes("text-h6")
            with ui.row().classes("w-full items-center gap-2") as self.stale_row:
                ui.icon("warning", color="warning")
                ui.label("This event changed elsewhere. Reload before saving.").classes(
                    "text-warning text-caption flex-1"
                )
                ui.button("Reload", on_click=self._reload).props("flat dense")
            self.timestamp = ui.input("Timestamp", on_change=self._mark_dirty).classes("w-full")
            self.source = ui.select(
                [source.value for source in DeviceSource],
                label="Source",
                on_change=self._mark_dirty,
            ).classes("w-full")
            self.kind = ui.select(
                [kind.value for kind in EventKind],
                label="Kind",
                on_change=self._mark_dirty,
            ).classes("w-full")
            self.category = ui.input("Category", on_change=self._mark_dirty).classes("w-full")
            self.name = ui.input("Name", on_change=self._mark_dirty).classes("w-full")

            with ui.row().classes("w-full justify-between"):
                self.delete_button = ui.button("Delete", on_click=self._delete).props("color=negative")
                with ui.row():
                    ui.button("Cancel", on_click=self.dialog.close).props("flat")
                    self.save_button = ui.button("Save", on_click=self._save)
        self.stale_row.set_visibility(False)

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

        self._load_selected(selected)
        self.dialog.open()

    def _load_selected(self, selected: Event):
        self.selected_event = selected
        self._loading = True
        try:
            self.timestamp.set_value(str(selected.timestamp))
            self.source.set_value(selected.device_source.value)
            self.kind.set_value(selected.event_kind.value)
            self.category.set_value(selected.category or "")
            self.name.set_value(selected.name or "")
        finally:
            self._loading = False
        self.dirty = False
        self._set_stale(False)

    def _mark_dirty(self, _=None):
        if not self._loading:
            self.dirty = True

    def _set_stale(self, stale: bool):
        self.stale = stale
        self.stale_row.set_visibility(stale)
        if stale:
            self.save_button.props("disable")
            self.delete_button.props("disable")
        else:
            self.save_button.props(remove="disable")
            self.delete_button.props(remove="disable")

    def _reload(self):
        if self.timeline is None or self.selected_event is None or self.selected_event.id is None:
            return
        selected = self.timeline.repo.get(Event, self.selected_event.id)
        if selected is None:
            self.dialog.close()
            self.selected_event = None
            ui.notify("Event was deleted in another connection", type="warning")
            return
        self._load_selected(selected)

    def database_changed(self):
        if self.timeline is None or self.selected_event is None or self.selected_event.id is None:
            return
        current = self.timeline.repo.get(Event, self.selected_event.id)
        if current is None or current.revision != self.selected_event.revision:
            if self.dirty:
                self._set_stale(True)
            elif current is None:
                self.dialog.close()
                self.selected_event = None
            else:
                self._load_selected(current)

    async def _save(self):
        if self.selected_event is None or self.timeline is None:
            return

        if self.stale:
            return

        try:
            updated = Event(
                id=self.selected_event.id,
                revision=self.selected_event.revision,
                timestamp=parse_event_timestamp(self.timestamp.value),
                device_source=DeviceSource(self.source.value),
                event_kind=EventKind(self.kind.value),
                category=self.category.value or None,
                name=self.name.value or None,
            )
        except ValueError:
            ui.notify("Timestamp, source, or kind is invalid", type="negative")
            return

        try:
            if self.mutation_api is None:
                self.timeline.repo.update(updated)
                warnings = rebuild_chunks_for_repo(self.timeline.repo)
            else:
                result = await self.mutation_api.update_event(updated, updated.revision)
                warnings = list(result.warnings)
        except ConcurrentModificationError:
            self._set_stale(True)
            ui.notify("Event changed elsewhere; reload before saving", type="warning")
            return

        self.selected_event = updated
        self.dirty = False
        self.dialog.close()
        if self.on_change is not None:
            self.on_change()
        notify_event_change("Event updated", warnings)

    async def _delete(self):
        if self.selected_event is None or self.selected_event.id is None or self.timeline is None:
            return

        if self.stale:
            return

        try:
            if self.mutation_api is None:
                self.timeline.repo.delete(Event, self.selected_event.id)
                warnings = rebuild_chunks_for_repo(self.timeline.repo)
            else:
                result = await self.mutation_api.delete_event(
                    self.selected_event.id,
                    self.selected_event.revision,
                )
                warnings = list(result.warnings)
        except ConcurrentModificationError:
            self._set_stale(True)
            ui.notify("Event changed elsewhere; reload before deleting", type="warning")
            return

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
    def __init__(self, *, compact: bool = False, framed: bool = True, mutation_api=None):
        self.timeline: Timeline | None = None
        self.search_term = ""
        self.events: list[Event] = []
        self.compact = compact

        container = ui.card() if framed else ui.column()
        container_classes = "w-full"
        if compact and framed:
            container_classes += " shadow-sm border border-gray-200 bg-gray-50"

        with container.classes(container_classes):
            with ui.row().classes("w-full items-center justify-between"):
                title_classes = "text-subtitle2 text-grey-8" if compact else "text-h6"
                ui.label("Event Viewer" if compact else "Events").classes(title_classes)
                self.count = ui.label("0 events").classes("text-caption text-grey-7")
            self.search = ui.input(
                "Search",
                placeholder="Timestamp, source, kind, category, name...",
                on_change=self._search_changed,
            ).props("clearable").classes("w-full")
            columns = [
                {"name": "timestamp", "label": "Time", "field": "timestamp"},
                {"name": "source", "label": "Source", "field": "source"},
                {"name": "name", "label": "Name", "field": "name"},
            ] if compact else [
                {"name": "id", "label": "ID", "field": "id"},
                {"name": "timestamp", "label": "Timestamp", "field": "timestamp"},
                {"name": "source", "label": "Source", "field": "source"},
                {"name": "kind", "label": "Kind", "field": "kind"},
                {"name": "category", "label": "Category", "field": "category"},
                {"name": "name", "label": "Name", "field": "name"},
            ]
            self.table = ui.table(
                columns=columns,
                rows=[],
                row_key="id",
                pagination={
                    "rowsPerPage": 10 if compact else 25,
                    "sortBy": "timestamp",
                    "descending": True,
                },
            ).classes("w-full text-caption" if compact else "w-full")
            if not compact:
                self.table.props(
                    "dense flat "
                    + visible_columns_expression(
                        ["timestamp", "source", "name"],
                        [column["name"] for column in columns],
                    )
                ).classes("bh-responsive-table")
            self.table.on("rowClick", self._row_clicked)

        self.editor = EventEditor(on_change=self._editor_changed, mutation_api=mutation_api)

    def update(self, timeline: Timeline):
        self.timeline = timeline
        self.events = timeline.events()
        self._render_rows()

    def database_changed(self, timeline: Timeline):
        self.update(timeline)
        self.editor.database_changed()

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
