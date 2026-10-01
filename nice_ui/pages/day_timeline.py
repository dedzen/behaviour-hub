from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import hashlib
from html import escape

from nicegui import ui

from timeline.api.timeline import Timeline
from timeline.domain.models import Chunk, DayMarker, Event, Point
from timeline.storage.repository import SQLiteRepository
from timeline.storage.errors import ConcurrentModificationError
from timeline.statistics.tools import human_duration
from nice_ui.pages.events import EventEditor, rebuild_chunks_for_repo, notify_event_change


DAY_SECONDS = 24 * 60 * 60
LANE_COLORS = [
    "#2563eb",
    "#16a34a",
    "#dc2626",
    "#9333ea",
    "#ca8a04",
    "#0891b2",
]


@dataclass(frozen=True, slots=True)
class TimelineBlock:
    source: str
    label: str
    start_percent: float
    width_percent: float
    color: str
    title: str
    label_mode: str
    start_event_id: int | None
    end_event_id: int | None


@dataclass(frozen=True, slots=True)
class TimelinePoint:
    source: str
    label: str
    left_percent: float
    title: str
    event_id: int | None


def seconds_into_day(value: datetime, day: date) -> int:
    start = datetime.combine(day, time.min)
    return max(0, min(DAY_SECONDS, int((value - start).total_seconds())))


def percent_into_day(value: datetime, day: date) -> float:
    return seconds_into_day(value, day) / DAY_SECONDS * 100


def chunk_blocks(timeline: Timeline, day: date) -> list[TimelineBlock]:
    df = timeline.day(day).to_clipped_polars()

    if df.is_empty():
        return []

    blocks = []

    for row in df.to_dicts():
        source = row["source"]
        start = row["start_timestamp"]
        end = row["end_timestamp"]
        start_percent = percent_into_day(start, day)
        end_percent = percent_into_day(end, day)
        label = row.get("name") or "Untitled"
        category = row.get("category")
        color = color_for_activity(source, label)

        blocks.append(
            TimelineBlock(
                source=source,
                label=label,
                start_percent=start_percent,
                width_percent=max(0.08, end_percent - start_percent),
                color=color,
                title=(
                    f"{source}: {label}"
                    f"{f' ({category})' if category else ''}\n"
                    f"{start:%H:%M} - {end:%H:%M}"
                ),
                label_mode="inside" if end_percent - start_percent >= 5 else "above",
                start_event_id=row.get("start_event_id"),
                end_event_id=row.get("end_event_id"),
            )
        )

    return blocks


def color_for_activity(source: str, name: str) -> str:
    digest = hashlib.sha1(f"{source}:{name}".encode("utf-8")).digest()
    return LANE_COLORS[digest[0] % len(LANE_COLORS)]


def point_markers(timeline: Timeline, day: date) -> list[TimelinePoint]:
    points = timeline.day(day).duration(minimum=None, maximum=None).points()
    return [point_marker(point, day) for point in points]


def point_marker(point: Point, day: date) -> TimelinePoint:
    label = " · ".join(part for part in [point.name, point.category] if part)
    return TimelinePoint(
        source=point.source.value,
        label=label or "Point",
        left_percent=percent_into_day(point.timestamp, day),
        title=f"{point.source.value}: {label or 'Point'}\n{point.timestamp:%H:%M}",
        event_id=point.event_id,
    )


def find_chunk_by_event_ids(repo: SQLiteRepository, event_ids: list[int]) -> Chunk | None:
    selected = set(event_ids)
    if not selected:
        return None

    for chunk in repo.load_chunks():
        chunk_event_ids = {chunk.start_event_id, chunk.end_event_id}
        if selected <= chunk_event_ids:
            return chunk

    return None


def remove_chunk_source_events(repo: SQLiteRepository, event_ids: list[int]) -> list[str]:
    repo._delete_chunks()
    for event_id in sorted(set(event_ids)):
        repo.delete(Event, event_id)
    repo.commit()
    return rebuild_chunks_for_repo(repo)


def format_people_text(people: list[str]) -> str:
    return "\n".join(people)


def parse_people_text(value: str) -> list[str]:
    people: list[str] = []
    seen: set[str] = set()
    for raw_item in value.replace(",", "\n").splitlines():
        item = raw_item.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        people.append(item)
    return people


def parse_mood_value(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def month_bounds(day: date) -> tuple[date, date]:
    start = day.replace(day=1)
    if day.month == 12:
        end = date(day.year + 1, 1, 1)
    else:
        end = date(day.year, day.month + 1, 1)
    return start, end


def habit_values_for_day(
    month_habits: set[str],
    day_habits: dict[str, bool],
) -> dict[str, bool]:
    return {
        habit: day_habits.get(habit, False)
        for habit in sorted(month_habits | set(day_habits))
    }


def month_habit_names(repo: SQLiteRepository, day: date) -> set[str]:
    start, end = month_bounds(day)
    return {
        habit
        for marker in repo.load_day_markers(start=start, end=end - timedelta(days=1))
        for habit in marker.habits
    }


def render_day_timeline_html(
    *,
    day: date,
    blocks: list[TimelineBlock],
    points: list[TimelinePoint],
) -> str:
    sources = sorted({block.source for block in blocks} | {point.source for point in points})

    if not sources:
        return f"""
        <div class="day-timeline">
          <style>{timeline_css()}</style>
          <div class="timeline-date">{escape(day.isoformat())}</div>
          <div class="empty-state">No chunks or points for this day.</div>
        </div>
        """

    hour_labels = "".join(
        f'<div class="hour-label" style="top:{hour / 24 * 100:.6f}%">'
        f'{format_hour(hour)}</div>'
        for hour in range(24)
    )
    hour_lines = "".join(
        f'<div class="hour-line" style="top:{hour / 24 * 100:.6f}%"></div>'
        for hour in range(25)
    )
    source_headers = "".join(
        f'<div class="source-header">{escape(source)}</div>'
        for source in sources
    )
    columns = []
    for source in sources:
        column_blocks = "".join(
            f'<div class="chunk {block.label_mode}" title="{escape(block.title)}" '
            f'data-event-ids="{event_ids_attribute(block.start_event_id, block.end_event_id)}" '
            f'style="top:{block.start_percent:.6f}%;'
            f'height:{block.width_percent:.6f}%;'
            f'--chunk-color:{block.color};">'
            f'<span>{escape(block.label)}</span></div>'
            for block in blocks
            if block.source == source
        )
        column_points = "".join(
            f'<div class="point" title="{escape(point.title)}" '
            f'data-event-ids="{event_ids_attribute(point.event_id)}" '
            f'style="top:{point.left_percent:.6f}%;">'
            f'<span>{escape(point.label)}</span></div>'
            for point in points
            if point.source == source
        )
        columns.append(
            f"""
            <div class="day-column">
              {column_blocks}
              {column_points}
            </div>
            """
        )

    grid_columns = f"72px repeat({len(sources)}, minmax(180px, 1fr))"

    return f"""
    <div class="day-timeline">
      <style>{timeline_css()}</style>
      <div class="timeline-date">{escape(day.isoformat())}</div>
      <div class="calendar" style="grid-template-columns:{grid_columns};">
        <div class="corner"></div>
        {source_headers}
        <div class="time-axis">
          {hour_labels}
        </div>
        <div class="calendar-body" style="grid-column:2 / span {len(sources)};">
          {hour_lines}
          <div class="columns" style="grid-template-columns:repeat({len(sources)}, minmax(180px, 1fr));">
            {''.join(columns)}
          </div>
        </div>
      </div>
    </div>
    """


def event_ids_attribute(*event_ids: int | None) -> str:
    return ",".join(str(event_id) for event_id in event_ids if event_id is not None)


def format_hour(hour: int) -> str:
    if hour == 0:
        return "12 AM"
    if hour < 12:
        return f"{hour} AM"
    if hour == 12:
        return "12 PM"
    return f"{hour - 12} PM"


def timeline_css() -> str:
    return """
    .day-timeline {
      width: 100%;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #111827;
    }
    .timeline-date {
      font-size: 13px;
      color: #4b5563;
      margin-bottom: 10px;
    }
    .empty-state {
      min-height: 160px;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 1px dashed #cbd5e1;
      background: #f8fafc;
      color: #64748b;
    }
    .calendar {
      display: grid;
      min-width: 760px;
      border: 1px solid #d1d5db;
      border-bottom: 0;
      background: #ffffff;
    }
    .corner,
    .source-header {
      height: 34px;
      border-bottom: 1px solid #d1d5db;
      background: #f8fafc;
    }
    .source-header {
      display: flex;
      align-items: center;
      justify-content: center;
      border-left: 1px solid #e5e7eb;
      font-size: 13px;
      font-weight: 600;
      color: #374151;
      text-transform: capitalize;
    }
    .time-axis,
    .calendar-body {
      position: relative;
      height: 1440px;
      border-bottom: 1px solid #d1d5db;
    }
    .time-axis {
      background: #ffffff;
    }
    .hour-label {
      position: absolute;
      right: 10px;
      transform: translateY(-8px);
      color: #374151;
      font-size: 12px;
      line-height: 16px;
      white-space: nowrap;
    }
    .calendar-body {
      overflow: hidden;
      border-left: 1px solid #d1d5db;
      background: #ffffff;
    }
    .hour-line {
      position: absolute;
      left: 0;
      right: 0;
      height: 1px;
      background: #dbe2ea;
    }
    .columns {
      position: absolute;
      inset: 0;
      display: grid;
    }
    .day-column {
      position: relative;
      border-left: 1px solid #eef2f7;
    }
    .day-column:first-child {
      border-left: 0;
    }
    .chunk {
      position: absolute;
      left: 6px;
      right: 6px;
      min-height: 18px;
      border-radius: 4px;
      background: var(--chunk-color);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.25);
      display: flex;
      align-items: flex-start;
      overflow: hidden;
      cursor: pointer;
    }
    .chunk span {
      display: block;
      width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      font-size: 12px;
      line-height: 15px;
      font-weight: 600;
      padding: 4px 6px;
    }
    .chunk.inside span {
      color: white;
      text-shadow: 0 1px 1px rgba(0, 0, 0, 0.35);
    }
    .chunk.above span {
      color: white;
      text-shadow: 0 1px 1px rgba(0, 0, 0, 0.35);
    }
    .point {
      position: absolute;
      left: 10px;
      right: 10px;
      height: 2px;
      background: #111827;
      transform: translateY(-1px);
      cursor: pointer;
    }
    .point::before {
      content: "";
      position: absolute;
      top: -4px;
      left: -1px;
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: #f59e0b;
      border: 2px solid #111827;
      box-sizing: border-box;
    }
    .point span {
      position: absolute;
      top: -8px;
      left: 16px;
      max-width: 160px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 11px;
      color: #111827;
    }
    """


class DayTimelineView:
    def __init__(
        self,
        *,
        on_day_change=None,
        on_marker_saved=None,
        note_editor_visible: bool = False,
        mutation_api=None,
    ):
        self.timeline: Timeline | None = None
        self.selected_day = date.today()
        self.on_day_change = on_day_change
        self.on_marker_saved = on_marker_saved
        self._syncing_day_input = False
        self.note_editor_visible = note_editor_visible
        self.mutation_api = mutation_api
        self.marker_revision = 0
        self.marker_dirty = False
        self.marker_stale = False
        self._loading_marker = False
        self._saving_marker: DayMarker | None = None
        self._chunk_event_revisions: dict[int, int] = {}

        with ui.column().classes("w-full gap-4"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Day Timeline").classes("text-h6")
                with ui.row().classes("items-center gap-1"):
                    with ui.button(
                        icon="chevron_left",
                        on_click=lambda: self._move_day(-1),
                    ).props("flat round dense").classes("day-switch-previous"):
                        ui.tooltip("Previous day")
                    self.day_input = ui.input(
                        "Day",
                        value=self.selected_day.isoformat(),
                        on_change=self._day_changed,
                    ).props("type=date").classes("w-44")
                    with ui.button(
                        icon="chevron_right",
                        on_click=lambda: self._move_day(1),
                    ).props("flat round dense").classes("day-switch-next"):
                        ui.tooltip("Next day")

            with ui.row().classes("w-full gap-4 items-stretch"):
                with ui.card().classes("flex-[3] min-w-0"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Day Marker").classes("text-subtitle1")
                        self.marker_save_button = ui.button(
                            "Save",
                            icon="save",
                            on_click=self._save_marker,
                        ).props("outline dense").classes("day-marker-save-action")
                    with ui.row().classes("w-full items-center gap-2") as self.marker_stale_row:
                        ui.icon("warning", color="warning")
                        ui.label(
                            "This marker changed elsewhere. Reload before saving."
                        ).classes("text-warning text-caption flex-1")
                        ui.button("Reload", on_click=self._reload_marker).props("flat dense")
                    with ui.row().classes("w-full gap-3 items-start"):
                        with ui.column().classes("min-w-[12rem] flex-1 gap-1"):
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label("Habits").classes("text-subtitle2 text-grey-7")
                                with ui.button(
                                    icon="add",
                                    on_click=self._toggle_habit_input,
                                ).props("flat round dense"):
                                    ui.tooltip("Add habit")
                            with ui.row().classes("w-full gap-2") as self.new_habit_row:
                                self.new_habit_input = ui.input("Habit").classes("flex-1")
                                ui.button(
                                    icon="check",
                                    on_click=self._add_habit,
                                ).props("outline round dense")
                            with ui.column().classes("w-full gap-1") as self.habits_container:
                                pass
                        with ui.column().classes("w-40 gap-1"):
                            self.mood_input = ui.number(
                                "Mood", on_change=self._mark_marker_dirty
                            ).classes("w-full")
                            self.people_input = ui.textarea(
                                "People", on_change=self._mark_marker_dirty
                            ).classes("w-full")
                        with ui.column().classes("min-w-[16rem] flex-[2] gap-1"):
                            ui.label("Quick note").classes("text-subtitle2 text-grey-7")
                            with ui.column().classes("w-full gap-2") as self.quick_note_editor_panel:
                                self.quick_note_input = ui.codemirror(
                                    "",
                                    language="Markdown",
                                    line_wrapping=True,
                                    on_change=self._quick_note_changed,
                                ).classes("w-full h-40 border border-slate-200 rounded")
                            self.quick_note_preview = ui.markdown("").classes(
                                "w-full min-h-[5rem] border border-slate-200 rounded p-2"
                            )
                with ui.card().classes("flex-1 min-w-[10rem]"):
                    pass

            with ui.card().classes("w-full overflow-x-auto"):
                self.container = ui.html("", sanitize=False).classes("w-full")
                self.container.on(
                    "click",
                    self._calendar_clicked,
                    js_handler="""
                    (event) => {
                      const target = event.target.closest('[data-event-ids]');
                      if (target && target.dataset.eventIds) {
                        emit(target.dataset.eventIds);
                      }
                    }
                    """,
                )

        self.editor = EventEditor(on_change=self._render, mutation_api=mutation_api)
        self.habit_inputs = {}
        self.new_habit_row.set_visibility(False)
        self.marker_stale_row.set_visibility(False)
        self.set_note_editor_visible(self.note_editor_visible)
        self._load_marker_form()
        with ui.dialog() as self.chunk_detail_dialog, ui.card().classes("w-[30rem] max-w-full"):
            ui.label("Chunk Details").classes("text-h6")
            with ui.column().classes("w-full gap-2") as self.chunk_detail_content:
                pass

    def update(self, timeline: Timeline):
        self.timeline = timeline
        if timeline.query.start is not None:
            self.set_day(
                Timeline._query_datetime(timeline.query.start).date(), # type: ignore
                notify=False,
            )
            return

        self._load_marker_form()
        self._render()

    def set_day(self, day: date, *, notify: bool = True):
        self.selected_day = day
        self._syncing_day_input = True
        try:
            self.day_input.set_value(self.selected_day.isoformat())
        finally:
            self._syncing_day_input = False
        self._load_marker_form()
        self._render()
        if notify and self.on_day_change is not None:
            self.on_day_change(self.selected_day)

    def _move_day(self, days: int):
        self.set_day(self.selected_day + timedelta(days=days))

    def _day_changed(self, event):
        if self._syncing_day_input:
            return

        try:
            selected_day = date.fromisoformat(event.value)
        except ValueError:
            ui.notify("Day must be a valid date", type="negative")
            return

        self.set_day(selected_day)

    def _load_marker_form(self):
        marker = self.timeline.day_marker(self.selected_day) if self.timeline is not None else None
        day_habits = marker.habits if marker is not None else {}
        month_habits = (
            month_habit_names(self.timeline.repo, self.selected_day)
            if self.timeline is not None
            else set()
        )
        self._loading_marker = True
        try:
            self._render_habits(habit_values_for_day(month_habits, day_habits))
            self.people_input.set_value(format_people_text(marker.people) if marker is not None else "")
            self.quick_note_input.set_value(marker.quick_note_markdown if marker is not None else "")
            self._set_quick_note_preview(marker.quick_note_markdown if marker is not None else "")
            self.mood_input.set_value(marker.mood if marker is not None else None)
        finally:
            self._loading_marker = False
        self.marker_revision = marker.revision if marker is not None else 0
        self.marker_dirty = False
        self._set_marker_stale(False)

    def set_note_editor_visible(self, visible: bool):
        self.note_editor_visible = visible
        self.quick_note_editor_panel.set_visibility(visible)

    def _quick_note_changed(self, event):
        self._mark_marker_dirty()
        self._set_quick_note_preview(event.value or "")

    def _set_quick_note_preview(self, value: str):
        self.quick_note_preview.set_content(value)

    def _render_habits(self, habits: dict[str, bool]):
        self.habits_container.clear()
        self.habit_inputs = {}
        with self.habits_container:
            for name in sorted(habits):
                self.habit_inputs[name] = ui.checkbox(
                    name,
                    value=habits[name],
                    on_change=self._mark_marker_dirty,
                )

    def _toggle_habit_input(self):
        self.new_habit_row.set_visibility(not self.new_habit_row.visible)

    def _add_habit(self):
        name = (self.new_habit_input.value or "").strip()
        if not name:
            self.new_habit_row.set_visibility(False)
            return

        habits = self._current_habits()
        habits.setdefault(name, False)
        self.new_habit_input.set_value("")
        self.new_habit_row.set_visibility(False)
        self._render_habits(habits)
        self._mark_marker_dirty()

    def _current_habits(self) -> dict[str, bool]:
        return {
            name: bool(checkbox.value)
            for name, checkbox in self.habit_inputs.items()
        }

    def _mark_marker_dirty(self, _=None):
        if not self._loading_marker:
            self.marker_dirty = True

    def _set_marker_stale(self, stale: bool):
        self.marker_stale = stale
        self.marker_stale_row.set_visibility(stale)
        if stale:
            self.marker_save_button.props("disable")
        else:
            self.marker_save_button.props(remove="disable")

    def _reload_marker(self):
        self._load_marker_form()

    async def _save_marker(self):
        if self.timeline is None:
            return

        if self.marker_stale:
            return

        try:
            marker = DayMarker(
                day=self.selected_day,
                habits=self._current_habits(),
                people=parse_people_text(self.people_input.value or ""),
                quick_note_markdown=self.quick_note_input.value or "",
                mood=parse_mood_value(self.mood_input.value),
                revision=self.marker_revision,
            )
        except ValueError:
            ui.notify("Mood must be numeric", type="negative")
            return

        try:
            if self.mutation_api is None:
                self.timeline.save_day_marker(marker)
                self.timeline.repo.commit()
            else:
                self._saving_marker = marker
                await self.mutation_api.save_day_marker(marker, self.marker_revision)
        except ConcurrentModificationError:
            self._set_marker_stale(True)
            ui.notify("Day marker changed elsewhere; reload before saving", type="warning")
            return
        finally:
            self._saving_marker = None

        self.marker_revision = marker.revision
        self.marker_dirty = False
        self._set_marker_stale(False)
        if self.on_marker_saved is not None:
            self.on_marker_saved(self.selected_day)
        ui.notify("Day marker saved", type="positive")

    def database_changed(self, *, events_changed: bool, marker_days: frozenset[date]):
        if events_changed:
            self.editor.database_changed()
            self._render()
        if self.selected_day not in marker_days:
            return
        current = self.timeline.day_marker(self.selected_day) if self.timeline is not None else None
        current_revision = current.revision if current is not None else 0
        if self._saving_marker is not None:
            self.marker_revision = self._saving_marker.revision
            return
        if current_revision == self.marker_revision:
            return
        if self.marker_dirty:
            self._set_marker_stale(True)
        else:
            self._load_marker_form()

    def _render(self):
        if self.timeline is None:
            return

        day_timeline = self.timeline.day(self.selected_day)
        self.container.set_content(
            render_day_timeline_html(
                day=self.selected_day,
                blocks=chunk_blocks(day_timeline, self.selected_day),
                points=point_markers(day_timeline, self.selected_day),
            )
        )

    def _calendar_clicked(self, event):
        if self.timeline is None or not event.args:
            return

        raw_event_ids = event.args[0] if isinstance(event.args, list) else event.args
        event_ids = [
            int(event_id)
            for event_id in str(raw_event_ids or "").split(",")
            if event_id
        ]

        if not event_ids:
            return

        if len(event_ids) == 1:
            self.editor.open(self.timeline, event_ids[0])
            return

        self._open_chunk_details(event_ids)

    def _open_chunk_details(self, event_ids: list[int]):
        if self.timeline is None:
            return

        self.chunk_detail_content.clear()
        self._chunk_event_revisions = {
            event_id: event.revision
            for event_id in event_ids
            if (event := self.timeline.repo.get(Event, event_id)) is not None
        }
        chunk = find_chunk_by_event_ids(self.timeline.repo, event_ids)
        labels = ["Start event", "End event"]

        with self.chunk_detail_content:
            if chunk is None:
                ui.label("Chunk was not found for these events.").classes("text-body2 text-grey-7")
            else:
                self._chunk_details(chunk)
                ui.separator()

            ui.label("Source Events").classes("text-subtitle2 text-grey-7")
            for label, event_id in zip(labels, event_ids, strict=False):
                ui.button(
                    label,
                    icon="edit",
                    on_click=lambda selected_id=event_id: self._open_chosen_event(selected_id), #type: ignore
                ).props("outline").classes("w-full")
            ui.separator()
            with ui.row().classes("w-full justify-between"):
                ui.button(
                    "Close",
                    on_click=self.chunk_detail_dialog.close,
                ).props("flat")
                ui.button(
                    "Remove chunk",
                    icon="delete",
                    on_click=lambda ids=event_ids: self._remove_chunk(ids), #type: ignore
                ).props("color=negative")

        self.chunk_detail_dialog.open()

    @staticmethod
    def _detail_row(label: str, value: str):
        with ui.row().classes("w-full justify-between gap-3"):
            ui.label(label).classes("text-caption text-grey-7")
            ui.label(value).classes("text-body2 text-right")

    def _chunk_details(self, chunk: Chunk):
        self._detail_row("Activity", chunk.name or "Untitled")
        self._detail_row("Category", chunk.category or "")
        self._detail_row("Source", chunk.source.value)
        self._detail_row("Start", chunk.start_timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        self._detail_row("End", chunk.end_timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        self._detail_row("Duration", human_duration(chunk.duration_seconds))
        self._detail_row("Chunk ID", str(chunk.id or ""))
        self._detail_row("Event IDs", f"{chunk.start_event_id}, {chunk.end_event_id}")

    async def _remove_chunk(self, event_ids: list[int]):
        if self.timeline is None:
            return

        try:
            if self.mutation_api is None:
                warnings = remove_chunk_source_events(self.timeline.repo, event_ids)
            else:
                if set(event_ids) != set(self._chunk_event_revisions):
                    raise ConcurrentModificationError("chunk events", ",".join(map(str, event_ids)))
                result = await self.mutation_api.delete_events(self._chunk_event_revisions)
                warnings = list(result.warnings)
        except ConcurrentModificationError:
            ui.notify("Chunk changed elsewhere; reopen it before deleting", type="warning")
            return
        self.chunk_detail_dialog.close()
        self._render()
        notify_event_change("Chunk source events deleted", warnings)

    def _open_chosen_event(self, event_id: int):
        if self.timeline is None:
            return

        self.chunk_detail_dialog.close()
        self.editor.open(self.timeline, event_id)
