from __future__ import annotations

import calendar as calendar_lib
from dataclasses import dataclass
from datetime import date, timedelta

from nicegui import ui

from nice_ui.keyboard_shortcuts import KeyboardShortcut, shortcut_script
from nice_ui.pages.day_timeline import DayTimelineView
from timeline.api.timeline import Timeline
from timeline.domain.models import DayMarker


@dataclass(frozen=True, slots=True)
class CalendarDaySummary:
    day: date
    in_month: bool
    is_today: bool
    is_selected: bool
    tracked_time: str
    screen_time: str
    mood: float | None
    has_note: bool
    people_count: int
    habits_done: int
    habits_total: int


@dataclass(frozen=True, slots=True)
class CalendarDayMetrics:
    day: date
    tracked_time: str
    screen_time: str
    mood: float | None
    has_note: bool
    people_count: int
    habits_done: int
    habits_total: int

    def with_state(
        self,
        *,
        visible_month: date,
        selected_day: date,
        today: date,
    ) -> CalendarDaySummary:
        return CalendarDaySummary(
            day=self.day,
            in_month=self.day.month == visible_month.month and self.day.year == visible_month.year,
            is_today=self.day == today,
            is_selected=self.day == selected_day,
            tracked_time=self.tracked_time,
            screen_time=self.screen_time,
            mood=self.mood,
            has_note=self.has_note,
            people_count=self.people_count,
            habits_done=self.habits_done,
            habits_total=self.habits_total,
        )


def month_start(day: date) -> date:
    return day.replace(day=1)


def shift_month(day: date, months: int) -> date:
    month_index = day.year * 12 + day.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    return date(year, month_zero + 1, 1)


def month_grid_dates(year: int, month: int) -> list[list[date]]:
    first = date(year, month, 1)
    start = first - timedelta(days=first.weekday())
    _, days_in_month = calendar_lib.monthrange(year, month)
    last = date(year, month, days_in_month)
    end = last + timedelta(days=6 - last.weekday())

    weeks: list[list[date]] = []
    cursor = start
    while cursor <= end:
        weeks.append([cursor + timedelta(days=offset) for offset in range(7)])
        cursor += timedelta(days=7)

    return weeks


def calendar_day_summary(
    timeline: Timeline,
    day: date,
    *,
    visible_month: date,
    selected_day: date,
    today: date,
) -> CalendarDaySummary:
    return calendar_day_metrics(timeline, day).with_state(
        visible_month=visible_month,
        selected_day=selected_day,
        today=today,
    )


def calendar_day_metrics(timeline: Timeline, day: date) -> CalendarDayMetrics:
    picture = timeline.day_picture(day)
    marker = picture.marker

    return CalendarDayMetrics(
        day=day,
        tracked_time=format_calendar_duration(picture.tracked_seconds),
        screen_time=format_calendar_duration(picture.active_screen_seconds),
        mood=marker.mood if marker is not None else None,
        has_note=_has_note(marker),
        people_count=len(marker.people) if marker is not None else 0,
        habits_done=_habits_done(marker),
        habits_total=len(marker.habits) if marker is not None else 0,
    )


def month_day_summaries(
    timeline: Timeline,
    visible_month: date,
    selected_day: date,
    today: date,
) -> list[CalendarDaySummary]:
    return [
        metric.with_state(
            visible_month=visible_month,
            selected_day=selected_day,
            today=today,
        )
        for metric in month_day_metrics(timeline, visible_month)
    ]


def month_day_metrics(
    timeline: Timeline,
    visible_month: date,
) -> list[CalendarDayMetrics]:
    return [
        calendar_day_metrics(timeline, day)
        for week in month_grid_dates(visible_month.year, visible_month.month)
        for day in week
    ]


def _has_note(marker: DayMarker | None) -> bool:
    return marker is not None and bool(marker.quick_note_markdown.strip())


def _habits_done(marker: DayMarker | None) -> int:
    if marker is None:
        return 0
    return sum(1 for value in marker.habits.values() if value)


def format_calendar_duration(seconds: int) -> str:
    total_minutes = max(0, int(seconds)) // 60
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d}"


class CalendarPage:
    def __init__(self, timeline: Timeline):
        self.timeline = timeline
        self.today = date.today()
        self.selected_day = self.today
        self.visible_month = month_start(self.selected_day)
        self.detail: DayTimelineView | None = None
        self._metrics_month: date | None = None
        self._metrics_by_day: dict[date, CalendarDayMetrics] = {}
        self.calendar_folded = False

        with ui.column().classes("w-full p-4 gap-4"):
            with ui.row().classes("w-full items-center justify-between gap-3"):
                ui.label("Calendar").classes("text-h5")
                with ui.row().classes("items-center gap-1"):
                    ui.button(
                        icon="chevron_left",
                        on_click=lambda: self._move_day(-1),
                    ).props("flat round dense").classes("calendar-prev-day-action hidden")
                    ui.button(
                        icon="chevron_right",
                        on_click=lambda: self._move_day(1),
                    ).props("flat round dense").classes("calendar-next-day-action hidden")
                    with ui.button(
                        icon="menu_open",
                        on_click=self._toggle_calendar_panel,
                    ).props("flat round dense").classes("calendar-fold-toggle") as self.fold_button:
                        ui.tooltip("Fold calendar")
                    ui.button(
                        icon="chevron_left",
                        on_click=lambda: self._move_month(-1),
                    ).props("flat round dense")
                    self.month_label = ui.label("").classes("text-subtitle1 min-w-[9rem] text-center")
                    ui.button(
                        icon="chevron_right",
                        on_click=lambda: self._move_month(1),
                    ).props("flat round dense")
                    ui.button(
                        "Today",
                        icon="today",
                        on_click=self._select_today,
                    ).props("outline dense")

            with ui.row().classes("w-full items-start gap-4"):
                with ui.column().classes("w-[28rem] max-w-full shrink-0 gap-3") as self.calendar_panel:
                    with ui.row().classes("items-center gap-1"):
                        ui.button("Day").props("unelevated dense color=primary")
                        with ui.button("Week").props("outline dense disable"):
                            ui.tooltip("Coming later")
                        with ui.button("Month").props("outline dense disable"):
                            ui.tooltip("Coming later")
                    self.month_grid = ui.grid(columns=7).classes("w-full gap-1")

                with ui.column().classes("flex-1 min-w-0 gap-3"):
                    self.detail = DayTimelineView(
                        on_day_change=self._detail_day_changed,
                        on_marker_saved=self._marker_saved,
                        note_editor_visible=self.calendar_folded,
                    )

        self.detail.update(self.timeline)
        self.detail.set_day(self.selected_day, notify=False)
        self._render_month_grid()
        ui.add_body_html(calendar_shortcut_script())

    def _toggle_calendar_panel(self):
        self.calendar_folded = not self.calendar_folded
        self.calendar_panel.set_visibility(not self.calendar_folded)
        self.fold_button.props(
            f"flat round dense icon={'calendar_month' if self.calendar_folded else 'menu_open'}"
        )
        if self.detail is not None:
            self.detail.set_note_editor_visible(self.calendar_folded)

    def _move_month(self, months: int):
        self.visible_month = shift_month(self.visible_month, months)
        self._refresh_month_metrics()
        self._render_month_grid()

    def _select_today(self):
        self._select_day(self.today)

    def _move_day(self, days: int):
        self._select_day(self.selected_day + timedelta(days=days))

    def _detail_day_changed(self, selected_day: date):
        self.selected_day = selected_day
        selected_month = month_start(selected_day)
        if selected_month != self.visible_month:
            self.visible_month = selected_month
            self._refresh_month_metrics()
        self._render_month_grid()

    def _select_day(self, selected_day: date):
        self.selected_day = selected_day
        selected_month = month_start(selected_day)
        if selected_month != self.visible_month:
            self.visible_month = selected_month
            self._refresh_month_metrics()
        if self.detail is not None:
            self.detail.set_day(selected_day, notify=False)
        self._render_month_grid()

    def _marker_saved(self, selected_day: date):
        self._metrics_by_day[selected_day] = calendar_day_metrics(self.timeline, selected_day)
        self._render_month_grid()

    def _refresh_month_metrics(self):
        self._metrics_month = self.visible_month
        self._metrics_by_day = {
            metric.day: metric
            for metric in month_day_metrics(self.timeline, self.visible_month)
        }

    def _render_month_grid(self):
        if self._metrics_month != self.visible_month:
            self._refresh_month_metrics()

        self.month_label.set_text(self.visible_month.strftime("%B %Y"))
        self.month_grid.clear()

        with self.month_grid:
            for label in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
                ui.label(label).classes("text-caption text-grey-7 text-center py-1")

            for week in month_grid_dates(self.visible_month.year, self.visible_month.month):
                for day in week:
                    metric = self._metrics_by_day[day]
                    summary = metric.with_state(
                        visible_month=self.visible_month,
                        selected_day=self.selected_day,
                        today=self.today,
                    )
                    self._day_cell(summary)

    def _day_cell(self, summary: CalendarDaySummary):
        classes = [
            "min-h-[5.4rem]",
            "p-1.5",
            "border",
            "text-left",
            "cursor-pointer",
            "rounded",
            "hover:bg-blue-50",
            "transition-colors",
        ]
        if summary.is_selected:
            classes.extend(["border-blue-600", "bg-blue-50"])
        elif summary.is_today:
            classes.extend(["border-slate-900", "bg-white"])
        else:
            classes.extend(["border-slate-200", "bg-white"])
        if not summary.in_month:
            classes.extend(["opacity-45"])

        with ui.column().classes(" ".join(classes)).on(
            "click",
            lambda _, selected_day=summary.day: self._select_day(selected_day),
        ):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(str(summary.day.day)).classes("text-sm font-medium")
                if summary.mood is not None:
                    ui.label(f"{summary.mood:g}").classes("text-xs text-blue-700")
            ui.label(f"T {summary.tracked_time}").classes("text-xs text-grey-8")
            ui.label(f"S {summary.screen_time}").classes("text-xs text-grey-8")
            with ui.row().classes("w-full items-center gap-1 text-grey-6"):
                if summary.has_note:
                    with ui.icon("edit").classes("text-[14px]"):
                        ui.tooltip("Quick note")
                if summary.people_count:
                    with ui.icon("person").classes("text-[14px]"):
                        ui.tooltip("People")
                    ui.label(str(summary.people_count)).classes("text-xs")


def marker_indicator_text(summary: CalendarDaySummary) -> str:
    parts: list[str] = []
    if summary.people_count:
        parts.append(str(summary.people_count))
    return " | ".join(parts)


def calendar_shortcut_script() -> str:
    return shortcut_script(
        "calendar",
        [
            KeyboardShortcut(
                key="c",
                selector=".calendar-fold-toggle",
            ),
            KeyboardShortcut(
                key="s",
                selector=".day-marker-save-action",
                ctrl=True,
                ignore_editable=False,
            ),
            KeyboardShortcut(
                key="ArrowLeft",
                selector=".calendar-prev-day-action",
            ),
            KeyboardShortcut(
                key="ArrowRight",
                selector=".calendar-next-day-action",
            ),
        ],
    )
