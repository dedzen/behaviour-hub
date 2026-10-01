from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from nicegui import ui

from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource
from timeline.statistics.tools import human_duration


PRESETS = [
    "All time", "Today", "Yesterday", "Last 7 days", "Last 30 days",
    "This week", "Last week", "This month", "Last month", "This year", "Custom...",
]


@dataclass
class FilterState:
    preset: str = "Today"
    start: date | None = None
    end: date | None = None
    activities: set[str] | None = None
    sources: set[str] | None = None
    min_duration: int | None = None
    max_duration: int | None = None


def resolved_date_range(
    state: FilterState,
    *,
    today: date | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Resolve a UI preset to a half-open datetime range."""
    today = today or date.today()
    tomorrow = today + timedelta(days=1)

    match state.preset:
        case "Today":
            start, end = today, tomorrow
        case "Yesterday":
            start, end = today - timedelta(days=1), today
        case "Last 7 days":
            start, end = today - timedelta(days=6), tomorrow
        case "Last 30 days":
            start, end = today - timedelta(days=29), tomorrow
        case "This week":
            start, end = today - timedelta(days=today.weekday()), tomorrow
        case "Last week":
            end = today - timedelta(days=today.weekday())
            start = end - timedelta(days=7)
        case "This month":
            start, end = today.replace(day=1), tomorrow
        case "Last month":
            end = today.replace(day=1)
            start = (end - timedelta(days=1)).replace(day=1)
        case "This year":
            start, end = date(today.year, 1, 1), tomorrow
        case "Custom...":
            if state.start is None or state.end is None:
                return None, None
            start, end = state.start, state.end + timedelta(days=1)
        case "All time":
            return None, None
        case _:
            raise ValueError(f"Unknown time preset: {state.preset}")

    return datetime.combine(start, time.min), datetime.combine(end, time.min)


def previous_date_range(
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    if start is None or end is None or end <= start:
        return None, None
    duration = end - start
    return start - duration, start


class FilterPanel:
    DEFAULT_DURATION = {"min": 0, "max": 12 * 3600}

    def __init__(self, timeline: Timeline, on_apply=None):
        self.base = timeline
        self.on_apply = on_apply
        self.state = FilterState(
            activities=set(),
            sources={DeviceSource.EMBED.value},
        )
        self._build()

    def timeline(self) -> Timeline:
        start, end = resolved_date_range(self.state)
        timeline = self.base.between(start, end)
        if self.state.activities:
            timeline = timeline.activity(self.state.activities)
        if self.state.sources:
            timeline = timeline.source([DeviceSource(value) for value in self.state.sources])
        if self.state.min_duration is not None or self.state.max_duration is not None:
            timeline = timeline.duration(
                minimum=self.state.min_duration,
                maximum=self.state.max_duration,
            )
        return timeline

    def _build(self) -> None:
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label("Filters").classes("text-h5")
            ui.button("Reset", on_click=self.reset).props("flat dense")

        self.preset = ui.select(
            PRESETS, value=self.state.preset, label="Time range", on_change=self._preset_changed,
        ).classes("w-full")
        with ui.row().classes("w-full gap-2") as self.custom_range:
            self.start_input = ui.input(
                "Start date", on_change=self._custom_dates_changed,
            ).props("type=date").classes("flex-1 min-w-0")
            self.end_input = ui.input(
                "End date", on_change=self._custom_dates_changed,
            ).props("type=date").classes("flex-1 min-w-0")
        self.range_error = ui.label().classes("text-negative text-caption")

        self.sources = ui.select(
            [source.value for source in DeviceSource],
            value=sorted(self.state.sources or ()), label="Activity sources", multiple=True,
            on_change=self._sources_changed,
        ).props("use-chips").classes("w-full")

        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Activities").classes("text-subtitle2")
            with ui.row().classes("gap-1"):
                ui.button("All", on_click=self._select_all_activities).props("flat dense")
                ui.button("Clear", on_click=self._clear_activities).props("flat dense")
        self.activity_search = ui.input(
            "Search activities", on_change=self._activity_search_changed,
        ).props("clearable dense").classes("w-full")
        self.activities = ui.tree(
            self._activity_tree_nodes(), tick_strategy="leaf", on_tick=self._activities_changed,
        ).classes("w-full")

        ui.label("Session duration").classes("text-subtitle2")
        self.duration_label = ui.label(self._duration_text()).classes("text-caption text-grey-7")
        self.duration_range = ui.range(
            min=0, max=12 * 3600, value=self.DEFAULT_DURATION.copy(),
            on_change=self._duration_changed,
        ).classes("w-full")
        self.apply_button = ui.button("Apply filters", icon="tune", on_click=self._apply)
        self.custom_range.set_visibility(False)
        self.range_error.set_visibility(False)

    def _activity_tree_nodes(self, search: str = "") -> list[dict]:
        needle = search.strip().lower()
        nodes: list[dict] = []
        for category, activities in self.base.metadata.activity_tree.items():
            children = [
                {"id": activity, "label": activity}
                for activity in activities
                if not needle or needle in activity.lower() or needle in category.lower()
            ]
            if children:
                nodes.append({"id": category, "label": category, "children": children})
        return nodes

    def _all_activity_names(self) -> set[str]:
        return {
            activity
            for activities in self.base.metadata.activity_tree.values()
            for activity in activities
        }

    def refresh_options(self) -> None:
        self.state.activities = set(self.state.activities or ()) & self._all_activity_names()
        self._refresh_activity_tree()

    def _refresh_activity_tree(self) -> None:
        self.activities.props["nodes"] = self._activity_tree_nodes(self.activity_search.value or "")
        self.activities.props["ticked"] = sorted(self.state.activities or ())
        self.activities.update()

    def summary_labels(self) -> list[str]:
        return [label for _, label in self.summary_items()]

    def summary_items(self) -> list[tuple[str, str]]:
        labels = [("time", self.state.preset)]
        sources = set(self.state.sources or ())
        labels.append(("sources",
            " + ".join(sorted(source.title() for source in sources))
            if sources else "No activity sources"
        ))
        activities = sorted(self.state.activities or ())
        if len(activities) == 1:
            labels.append(("activities", activities[0]))
        elif activities:
            labels.append(("activities", f"{len(activities)} activities"))
        minimum, maximum = self.state.min_duration, self.state.max_duration
        if minimum not in (None, 0) or maximum not in (None, self.DEFAULT_DURATION["max"]):
            labels.append(("duration",
                f"{human_duration(minimum or 0)}–"
                f"{human_duration(maximum or self.DEFAULT_DURATION['max'])}"
            ))
        return labels

    def range_label(self) -> str:
        if self.state.preset != "Custom...":
            return self.state.preset
        if self.state.start is None or self.state.end is None:
            return "Custom range"
        return f"{self.state.start:%b %d, %Y} – {self.state.end:%b %d, %Y}"

    def remove_summary(self, kind: str):
        if kind == "time":
            self.state.preset = "All time"
            self.preset.set_value("All time")
            self.custom_range.set_visibility(False)
        elif kind == "sources":
            self.state.sources = {DeviceSource.EMBED.value}
            self.sources.set_value([DeviceSource.EMBED.value])
        elif kind == "activities":
            self._clear_activities()
        elif kind == "duration":
            self.state.min_duration = None
            self.state.max_duration = None
            self.duration_range.set_value(self.DEFAULT_DURATION.copy())
            self.duration_label.set_text(self._duration_text())
        return self._apply()

    def reset(self):
        self.state = FilterState(activities=set(), sources={DeviceSource.EMBED.value})
        self.preset.set_value("Today")
        self.start_input.set_value(None)
        self.end_input.set_value(None)
        self.sources.set_value([DeviceSource.EMBED.value])
        self.activity_search.set_value("")
        self.duration_range.set_value(self.DEFAULT_DURATION.copy())
        self.duration_label.set_text(self._duration_text())
        self.custom_range.set_visibility(False)
        self._set_range_error(None)
        self._refresh_activity_tree()
        return self._apply()

    def _apply(self):
        error = self._validation_error()
        self._set_range_error(error)
        if not error and self.on_apply is not None:
            return self.on_apply()
        return None

    def _preset_changed(self, event) -> None:
        self.state.preset = event.value
        self.custom_range.set_visibility(event.value == "Custom...")
        self._set_range_error(self._validation_error())

    def _custom_dates_changed(self, _=None) -> None:
        self.state.start = self._parse_optional_date(self.start_input.value)
        self.state.end = self._parse_optional_date(self.end_input.value)
        self._set_range_error(self._validation_error())

    @staticmethod
    def _parse_optional_date(value: str | None) -> date | None:
        return date.fromisoformat(value) if value else None

    def _custom_range_error(self) -> str | None:
        if self.state.preset != "Custom...":
            return None
        if self.state.start is None or self.state.end is None:
            return "Choose both a start and end date."
        if self.state.end < self.state.start:
            return "End date must be on or after start date."
        return None

    def _validation_error(self) -> str | None:
        return self._custom_range_error() or (
            None if self.state.sources else "Choose at least one activity source."
        )

    def _set_range_error(self, error: str | None) -> None:
        self.range_error.set_text(error or "")
        self.range_error.set_visibility(bool(error))
        self.apply_button.props("disable" if error else "")
        if not error:
            self.apply_button.props(remove="disable")

    def _sources_changed(self, event) -> None:
        self.state.sources = set(event.value or ())
        self._set_range_error(self._validation_error())

    def _activities_changed(self, event) -> None:
        visible = {
            child["id"]
            for node in self._activity_tree_nodes(self.activity_search.value or "")
            for child in node.get("children", [])
        }
        hidden_selected = set(self.state.activities or ()) - visible
        self.state.activities = hidden_selected | set(event.value or ())

    def _activity_search_changed(self, _=None) -> None:
        self._refresh_activity_tree()

    def _select_all_activities(self) -> None:
        self.state.activities = self._all_activity_names()
        self._refresh_activity_tree()

    def _clear_activities(self) -> None:
        self.state.activities = set()
        self._refresh_activity_tree()

    def _duration_changed(self, event) -> None:
        self.state.min_duration = event.value["min"]
        self.state.max_duration = event.value["max"]
        self.duration_label.set_text(self._duration_text())

    def _duration_text(self) -> str:
        minimum = self.state.min_duration if self.state.min_duration is not None else 0
        maximum = (
            self.state.max_duration
            if self.state.max_duration is not None
            else self.DEFAULT_DURATION["max"]
        )
        return f"{human_duration(minimum)} – {human_duration(maximum)}"
