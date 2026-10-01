from dataclasses import dataclass
from datetime import date, timedelta

from nicegui import ui

from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource
from timeline.statistics.tools import human_duration

PRESETS = [
    "All time",
    "Today",
    "Yesterday",
    "Last 7 days",
    "Last 30 days",
    "This week",
    "Last week",
    "This month",
    "Last month",
    "This year",
    "Custom...",
]

@dataclass
class FilterState:
    preset: str = "All time"
    start: date | None = None
    end: date | None = None

    activities: set[str] | None = None
    sources: set[str] | None = None

    min_duration: int | None = None
    max_duration: int | None = None


class FilterPanel:
    DEFAULT_DURATION = {
        "min": 0,
        "max": 12 * 3600,
    }

    def __init__(self, timeline: Timeline, on_apply=None):
        self.base = timeline
        self.on_apply = on_apply
        self.state = FilterState(
            activities=set(),
            sources={DeviceSource.EMBED.value},
        )

        self._build()

    def timeline(self) -> Timeline:
        t = self.base

        if self.state.start:
            t = t.after(date.fromisoformat(self.state.start)) #type: ignore

        if self.state.end:
            t = t.before(date.fromisoformat(self.state.end)) #type: ignore

        if self.state.activities:
            t = t.activity(self.state.activities)

        if self.state.sources:
            t = t.source([DeviceSource(i) for i in self.state.sources])
        t= self._resolve_preset(t)

        if (
            self.state.min_duration is not None
            or self.state.max_duration is not None
        ):
            t = t.duration(
                minimum=self.state.min_duration,
                maximum=self.state.max_duration,
            )

        return t
    def _build(self):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label("Filters").classes("text-h5")
            self.phone_source = ui.checkbox(
                "Phone",
                value=False,
                on_change=lambda e: self._phone_source_changed(bool(e.value)),
            ).props("dense")

        self.preset = ui.select(
            PRESETS,
            value=self.state.preset,
            label="Time",
            on_change=self._preset_changed,
        ).classes("w-full")

        ui.label("Activities")

        tree = self._activity_tree_nodes()
        self.activities = ui.tree(
            tree,
            tick_strategy="leaf",
            on_tick=lambda e:
                setattr(
                    self.state,
                    "activities",
                    set(e.value),
                ),
        )
        self.duration_label = ui.label()
        self.range = ui.range(
            min=0,
            max=12 * 3600,
            value=self.DEFAULT_DURATION, # type: ignore
            on_change=self._duration_changed,
        ).classes("w-full")

        with ui.row().classes("w-full"):
            ui.button(
                "Apply",
                on_click=lambda: self.on_apply(), # type: ignore
            )
            ui.button(
                "Reset",
                on_click=self.reset,
            )

    def _activity_tree_nodes(self) -> list[dict]:
        return [
            {
                "id": category,
                "label": category,
                "children": [
                    {
                        "id": activity,
                        "label": activity,
                    }
                    for activity in activities
                ],
            }
            for category, activities in self.base.metadata.activity_tree.items()
        ]

    def refresh_options(self) -> None:
        selected = set(self.state.activities or ())
        nodes = self._activity_tree_nodes()
        available = {
            child["id"]
            for node in nodes
            for child in node.get("children", [])
        }
        selected &= available
        self.state.activities = selected
        self.activities.props["nodes"] = nodes
        self.activities.props["ticked"] = list(selected)
        self.activities.update()

    def reset(self):
        self.preset.set_value("All time")
        self.phone_source.set_value(False)
        self.activities.untick()
        self.range.set_value(self.DEFAULT_DURATION) #type:ignore 
        self.duration_label.set_text("")

        self.state = FilterState(
            activities=set(),
            sources={DeviceSource.EMBED.value},
        )

        if self.on_apply is not None:
            self.on_apply()

    def _preset_changed(self, e):
        self.state.preset = e.value
    def _phone_source_changed(self, include_phone: bool):
        sources = {DeviceSource.EMBED.value}
        if include_phone:
            sources.add(DeviceSource.PHONE.value)
        self.state.sources = sources
    def _duration_changed(self, e):
        minimum = e.value["min"]
        maximum = e.value["max"]

        self.state.min_duration = minimum
        self.state.max_duration = maximum

        self.duration_label.set_text(
            f"{human_duration(minimum)} – {human_duration(maximum)}"
        )
    def _resolve_preset(self, p):
        t = p

        match self.state.preset:
            case "Today":
                t = t.day(date.today())

            case "Yesterday":
                t = t.day(date.today() - timedelta(days=1))

            case "Last 7 days":
                t = t.last(days=7)

            case "Last 30 days":
                t = t.last(days=30)

            case "This week":
                t = t.week(date.today().isocalendar()[:2])

            case "Last week":
                today = date.today()
                last_week = today - timedelta(days=7)
                t = t.week(last_week.isocalendar()[:2])

            case "This month":
                t = t.month((date.today().year, date.today().month))

            case "Last month":
                today = date.today()
                year = today.year
                month = today.month - 1
                if month == 0:
                    month = 12
                    year -= 1
                t = t.month((year, month))

            case "This year":
                t = t.year(date.today().year)

            case "Custom...":
                if self.state.start:
                    t = t.after(self.state.start)
                if self.state.end:
                    t = t.before(self.state.end)

            case "All time":
                pass
        return t
    
