from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import hashlib
from html import escape

from nicegui import ui

from timeline.api.timeline import Timeline
from timeline.domain.models import Point
from nice_ui.pages.events import EventEditor


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
    def __init__(self):
        self.timeline: Timeline | None = None
        self.selected_day = date.today()

        with ui.column().classes("w-full gap-4"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Day Timeline").classes("text-h6")
                self.day_input = ui.input(
                    "Day",
                    value=self.selected_day.isoformat(),
                    on_change=self._day_changed,
                ).props("type=date").classes("w-44")

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

        self.editor = EventEditor(on_change=self._render)
        with ui.dialog() as self.event_choice_dialog, ui.card().classes("w-96 max-w-full"):
            ui.label("Edit Chunk Events").classes("text-h6")
            with ui.column().classes("w-full gap-2") as self.event_choice_buttons:
                pass

    def update(self, timeline: Timeline):
        self.timeline = timeline
        if timeline.query.start is not None:
            self.selected_day = Timeline._query_datetime(timeline.query.start).date() # type: ignore
            self.day_input.set_value(self.selected_day.isoformat())

        self._render()

    def _day_changed(self, event):
        try:
            self.selected_day = date.fromisoformat(event.value)
        except ValueError:
            ui.notify("Day must be a valid date", type="negative")
            return

        self._render()

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

        self._open_event_choice(event_ids)

    def _open_event_choice(self, event_ids: list[int]):
        if self.timeline is None:
            return

        self.event_choice_buttons.clear()
        labels = ["Start event", "End event"]

        with self.event_choice_buttons:
            for label, event_id in zip(labels, event_ids, strict=False):
                ui.button(
                    label,
                    icon="edit",
                    on_click=lambda selected_id=event_id: self._open_chosen_event(selected_id), #type: ignore
                ).props("outline").classes("w-full")

        self.event_choice_dialog.open()

    def _open_chosen_event(self, event_id: int):
        if self.timeline is None:
            return

        self.event_choice_dialog.close()
        self.editor.open(self.timeline, event_id)
