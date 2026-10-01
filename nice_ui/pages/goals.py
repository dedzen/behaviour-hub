from __future__ import annotations

from datetime import date, timedelta

from nicegui import ui

from nice_ui.runtime import DataChange, DashboardRuntime
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource
from timeline.goals.models import (
    ActivityDurationRule,
    GoalDefinition,
    GoalOperator,
    GoalPeriod,
    GoalSchedule,
    GoalSeries,
    GoalStatus,
    ProgressStatus,
)
from timeline.goals.periods import next_period_start, period_start, previous_period_start
from timeline.goals.repository import GoalRepository
from timeline.goals.service import progress_for_period
from timeline.statistics.tools import human_duration
from timeline.storage.errors import ConcurrentModificationError


STATUS_PRESENTATION = {
    ProgressStatus.SCHEDULED: ("Scheduled", "grey", "event"),
    ProgressStatus.IN_PROGRESS: ("In progress", "primary", "hourglass_top"),
    ProgressStatus.ON_TRACK: ("On track", "positive", "trending_flat"),
    ProgressStatus.MET: ("Met", "positive", "check_circle"),
    ProgressStatus.MISSED: ("Missed", "negative", "cancel"),
}


class GoalEditor:
    def __init__(self, timeline: Timeline, runtime: DashboardRuntime, on_saved):
        self.timeline = timeline
        self.runtime = runtime
        self.on_saved = on_saved
        self.definition: GoalDefinition | None = None
        self.loading = False

        with ui.dialog() as self.dialog, ui.card().classes(
            "bh-dialog-panel w-[38rem] max-w-full"
        ):
            with ui.row().classes("w-full items-center justify-between"):
                self.heading = ui.label("New goal").classes("text-h6")
                ui.button(icon="close", on_click=self.dialog.close).props("flat round dense")
            self.title = ui.input("Goal name").classes("w-full")
            with ui.row().classes("w-full gap-3 flex-col sm:flex-row"):
                self.schedule = ui.select(
                    [schedule.value for schedule in GoalSchedule],
                    value=GoalSchedule.RECURRING.value,
                    label="Schedule",
                    on_change=self._schedule_changed,
                ).classes("flex-1")
                self.period = ui.select(
                    [period.value for period in GoalPeriod],
                    value=GoalPeriod.DAY.value,
                    label="Period",
                    on_change=self._period_changed,
                ).classes("flex-1")
            with ui.row().classes("w-full gap-3 flex-col sm:flex-row"):
                self.start = ui.input("First period").props("type=date").classes("flex-1")
                self.end = ui.input("Last period (optional)").props("type=date").classes("flex-1")
            self.effective = ui.input("Changes apply from").props("type=date").classes("w-full")

            ui.separator()
            ui.label("Activity duration rule").classes("text-subtitle1")
            self.source = ui.select(
                [source.value for source in DeviceSource],
                value=DeviceSource.EMBED.value,
                label="Source",
                on_change=self._source_changed,
            ).classes("w-full")
            self.category = ui.select(
                [], label="Category", on_change=self._category_changed,
            ).classes("w-full")
            self.activity = ui.select([], label="Activity").classes("w-full")
            with ui.row().classes("w-full gap-3 flex-col sm:flex-row"):
                self.operator = ui.select(
                    {
                        GoalOperator.AT_LEAST.value: "At least",
                        GoalOperator.AT_MOST.value: "At most",
                    },
                    value=GoalOperator.AT_LEAST.value,
                    label="Target",
                ).classes("flex-1")
                self.amount = ui.number("Duration", value=1, min=0.01).classes("flex-1")
                self.unit = ui.select(
                    ["minutes", "hours"], value="hours", label="Unit"
                ).classes("w-32")
            self.error = ui.label().classes("text-negative text-caption")
            self.error.set_visibility(False)
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=self.dialog.close).props("flat")
                self.save_button = ui.button("Save goal", icon="save", on_click=self._save)

        self._refresh_categories()
        self._schedule_changed()

    def open_new(self, selected: date, period: GoalPeriod) -> None:
        self.definition = None
        self.heading.set_text("New goal")
        self.title.set_value("")
        self.schedule.set_value(GoalSchedule.RECURRING.value)
        self.period.set_value(period.value)
        self.start.set_value(period_start(period, selected).isoformat())
        self.end.set_value(None)
        self.effective.set_visibility(False)
        self.schedule.props(remove="disable")
        self.period.props(remove="disable")
        self.source.set_value(DeviceSource.EMBED.value)
        self.operator.set_value(GoalOperator.AT_LEAST.value)
        self.amount.set_value(1)
        self.unit.set_value("hours")
        self._set_error(None)
        self._refresh_categories()
        self.dialog.open()

    def open_edit(self, definition: GoalDefinition) -> None:
        self.definition = definition
        series, rule = definition.series, definition.rule
        self.loading = True
        try:
            self.heading.set_text("Edit goal")
            self.title.set_value(definition.version.title)
            self.schedule.set_value(series.schedule.value)
            self.period.set_value(series.period.value)
            self.start.set_value(series.start_period.isoformat())
            self.end.set_value(
                (series.end_period_exclusive - timedelta(days=1)).isoformat()
                if series.end_period_exclusive else None
            )
            self.effective.set_value(period_start(series.period, date.today()).isoformat())
            self.effective.set_visibility(series.schedule == GoalSchedule.RECURRING)
            self.schedule.props("disable")
            self.period.props("disable")
            self.source.set_value(rule.source.value)
            self._refresh_categories(rule.category, rule.activity)
            self.operator.set_value(rule.operator.value)
            if rule.target_seconds % 3600 == 0:
                self.amount.set_value(rule.target_seconds / 3600)
                self.unit.set_value("hours")
            else:
                self.amount.set_value(rule.target_seconds / 60)
                self.unit.set_value("minutes")
            self._set_error(None)
        finally:
            self.loading = False
        self.dialog.open()

    def _activity_tree(self) -> dict[str, list[str]]:
        try:
            source = DeviceSource(self.source.value)
        except (TypeError, ValueError):
            return {}
        return Timeline(self.timeline.repo).source(source).metadata.activity_tree

    def _refresh_categories(
        self,
        selected_category: str | None = None,
        selected_activity: str | None = None,
    ) -> None:
        tree = self._activity_tree()
        self.category.options = sorted(tree)
        self.category.update()
        category = selected_category if selected_category in tree else (
            self.category.options[0] if self.category.options else None
        )
        self.category.set_value(category)
        activities = sorted(tree.get(category, [])) if category else []
        self.activity.options = activities
        self.activity.update()
        self.activity.set_value(
            selected_activity if selected_activity in activities
            else activities[0] if activities else None
        )

    def _source_changed(self, _=None) -> None:
        if not self.loading:
            self._refresh_categories()

    def _category_changed(self, event) -> None:
        if self.loading:
            return
        activities = sorted(self._activity_tree().get(event.value, []))
        self.activity.options = activities
        self.activity.set_value(activities[0] if activities else None)
        self.activity.update()

    def _schedule_changed(self, _=None) -> None:
        recurring = self.schedule.value == GoalSchedule.RECURRING.value
        self.end.set_visibility(recurring and self.definition is None)

    def _period_changed(self, _=None) -> None:
        if self.start.value:
            selected = date.fromisoformat(self.start.value)
            self.start.set_value(period_start(GoalPeriod(self.period.value), selected).isoformat())

    def _set_error(self, message: str | None) -> None:
        self.error.set_text(message or "")
        self.error.set_visibility(bool(message))

    def _rule(self) -> ActivityDurationRule:
        multiplier = 3600 if self.unit.value == "hours" else 60
        return ActivityDurationRule(
            source=DeviceSource(self.source.value),
            category=self.category.value or "",
            activity=self.activity.value or "",
            operator=GoalOperator(self.operator.value),
            target_seconds=round(float(self.amount.value or 0) * multiplier),
        )

    async def _save(self) -> None:
        self.save_button.props("disable")
        try:
            if not (self.title.value or "").strip():
                raise ValueError("Goal name is required")
            rule = self._rule()
            if self.definition is None:
                if not self.start.value:
                    raise ValueError("First period is required")
                await self.runtime.create_goal(
                    schedule=GoalSchedule(self.schedule.value),
                    period=GoalPeriod(self.period.value),
                    selected_start=date.fromisoformat(self.start.value),
                    selected_end=date.fromisoformat(self.end.value) if self.end.value else None,
                    title=self.title.value.strip(),
                    rule=rule,
                )
            else:
                effective = (
                    date.fromisoformat(self.effective.value)
                    if self.effective.visible and self.effective.value
                    else self.definition.series.start_period
                )
                await self.runtime.revise_goal(
                    self.definition.series.id,
                    self.definition.series.revision,
                    effective_from=effective,
                    title=self.title.value.strip(),
                    rule=rule,
                )
        except (ValueError, ConcurrentModificationError) as exc:
            self._set_error(str(exc))
            return
        finally:
            self.save_button.props(remove="disable")
        self.dialog.close()
        self.on_saved()
        ui.notify("Goal saved", type="positive")


class GoalsPage:
    def __init__(
        self,
        timeline: Timeline,
        goal_repo: GoalRepository,
        runtime: DashboardRuntime,
    ):
        self.timeline = timeline
        self.goal_repo = goal_repo
        self.runtime = runtime
        self.period = GoalPeriod.DAY
        self.selected = date.today()
        self.pending_delete: GoalSeries | None = None

        with ui.column().classes("bh-page w-full p-4 gap-4"):
            with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
                with ui.column().classes("gap-0"):
                    ui.label("Goals").classes("text-h5")
                    ui.label("Track activity targets by calendar period").classes(
                        "text-caption text-grey-7"
                    )
                ui.button("New goal", icon="add", on_click=self._new_goal)

            with ui.card().classes("bh-card w-full"):
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    self.period_toggle = ui.toggle(
                        {GoalPeriod.DAY.value: "Day", GoalPeriod.WEEK.value: "Week"},
                        value=self.period.value,
                        on_change=self._period_changed,
                    )
                    ui.space()
                    ui.button(icon="chevron_left", on_click=lambda: self._move(-1)).props(
                        "flat round aria-label='Previous period'"
                    )
                    self.date_input = ui.input(
                        "Selected date", value=self.selected.isoformat(), on_change=self._date_changed,
                    ).props("type=date").classes("w-44")
                    ui.button(icon="chevron_right", on_click=lambda: self._move(1)).props(
                        "flat round aria-label='Next period'"
                    )
                    ui.button("Today", icon="today", on_click=self._today).props("outline")
                self.period_label = ui.label().classes("text-subtitle1")

            self.progress_container = ui.grid().classes(
                "w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3"
            )

            with ui.expansion("Manage goals", icon="settings", value=False).classes(
                "bh-card w-full bg-white"
            ):
                self.management = ui.column().classes("w-full gap-2")

        self.editor = GoalEditor(timeline, runtime, self.refresh)
        with ui.dialog() as self.delete_dialog, ui.card().classes(
            "bh-dialog-panel w-[30rem] max-w-full"
        ):
            ui.label("Delete goal permanently?").classes("text-h6")
            self.delete_message = ui.label()
            ui.label("All saved rule versions will be removed.").classes(
                "text-caption text-grey-7"
            )
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=self.delete_dialog.close).props("flat")
                ui.button("Delete", icon="delete_forever", on_click=self._delete).props(
                    "color=negative"
                )
        self.refresh()

    def database_changed(self, change: DataChange) -> None:
        if change.events_changed or change.goals_changed:
            self.refresh()

    def _selected_start(self) -> date:
        return period_start(self.period, self.selected)

    def _period_changed(self, event) -> None:
        self.period = GoalPeriod(event.value)
        self.selected = period_start(self.period, self.selected)
        self.date_input.set_value(self.selected.isoformat())
        self.refresh()

    def _date_changed(self, event) -> None:
        if not event.value:
            return
        self.selected = period_start(self.period, date.fromisoformat(event.value))
        if self.selected.isoformat() != event.value:
            self.date_input.set_value(self.selected.isoformat())
        self.refresh()

    def _move(self, direction: int) -> None:
        current = self._selected_start()
        self.selected = (
            next_period_start(self.period, current)
            if direction > 0 else previous_period_start(self.period, current)
        )
        self.date_input.set_value(self.selected.isoformat())
        self.refresh()

    def _today(self) -> None:
        self.selected = period_start(self.period, date.today())
        self.date_input.set_value(self.selected.isoformat())
        self.refresh()

    def _new_goal(self) -> None:
        self.editor.open_new(self._selected_start(), self.period)

    def refresh(self) -> None:
        selected = self._selected_start()
        if self.period == GoalPeriod.DAY:
            self.period_label.set_text(selected.strftime("%A, %B %d, %Y"))
        else:
            end = selected + timedelta(days=6)
            self.period_label.set_text(
                f"Week of {selected:%B %d, %Y} – {end:%B %d, %Y}"
            )
        self._render_progress()
        self._render_management()

    def _render_progress(self) -> None:
        items = progress_for_period(
            self.goal_repo, self.timeline, self.period, self._selected_start()
        )
        self.progress_container.clear()
        with self.progress_container:
            if not items:
                with ui.card().classes("bh-card col-span-full"):
                    ui.label("No goals for this period").classes("text-h6")
                    ui.label(
                        "Create a one-off or recurring activity-duration goal."
                    ).classes("text-body2 text-grey-7")
                    ui.button("Create goal", icon="add", on_click=self._new_goal).props("outline")
                return
            for progress in items:
                self._progress_card(progress)

    def _progress_card(self, progress) -> None:
        rule = progress.definition.rule
        label, color, icon = STATUS_PRESENTATION[progress.status]
        with ui.card().classes("bh-card w-full"):
            with ui.row().classes("w-full items-start justify-between gap-2"):
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(progress.definition.version.title).classes(
                        "text-subtitle1 font-medium truncate"
                    )
                    ui.label(
                        f"{rule.source.value.title()} · {rule.category} · {rule.activity}"
                    ).classes("text-caption text-grey-7")
                ui.badge(label, color=color).props(f"outline icon={icon}")
            operator = "at least" if rule.operator == GoalOperator.AT_LEAST else "at most"
            ui.label(
                f"{human_duration(progress.actual_seconds)} of {operator} "
                f"{human_duration(progress.target_seconds)}"
            ).classes("text-body1")
            ui.linear_progress(value=min(progress.ratio, 1.0), color=color).props(
                "rounded size=10px"
            )

    def _render_management(self) -> None:
        self.management.clear()
        series_items = self.goal_repo.list_series()
        with self.management:
            if not series_items:
                ui.label("No goal definitions yet.").classes("text-grey-7")
                return
            for series in series_items:
                versions = self.goal_repo.list_versions(series.id)
                if not versions:
                    continue
                current = period_start(series.period, date.today())
                reference = max(current, series.start_period)
                if series.end_period_exclusive and reference >= series.end_period_exclusive:
                    reference = previous_period_start(
                        series.period, series.end_period_exclusive
                    )
                definition = self.goal_repo.definition(series.id, reference)
                if definition is None:
                    definition = GoalDefinition(series, versions[-1])
                future_versions = sum(version.effective_from > current for version in versions)
                with ui.card().classes("w-full shadow-none border border-slate-200"):
                    with ui.row().classes("w-full items-center gap-3 flex-wrap"):
                        with ui.column().classes("gap-0 flex-1 min-w-[12rem]"):
                            ui.label(definition.version.title).classes("font-medium")
                            ui.label(
                                f"{series.schedule.value.replace('_', ' ').title()} · "
                                f"{series.period.value.title()} · {len(versions)} version(s)"
                            ).classes("text-caption text-grey-7")
                            if future_versions:
                                ui.label(
                                    f"{future_versions} scheduled revision(s)"
                                ).classes("text-caption text-primary")
                                with ui.column().classes("gap-0 pl-2"):
                                    for version in versions:
                                        if version.effective_from > current:
                                            ui.label(
                                                f"From {version.effective_from.isoformat()}: "
                                                f"{version.title}"
                                            ).classes("text-caption text-grey-7")
                        lifecycle_label = series.status.value.title()
                        if (
                            series.status == GoalStatus.ACTIVE
                            and series.end_period_exclusive is not None
                            and series.end_period_exclusive <= current
                        ):
                            lifecycle_label = "Completed"
                        ui.badge(lifecycle_label).props("outline")
                        if series.status == GoalStatus.ACTIVE:
                            ui.button(
                                icon="edit",
                                on_click=lambda _, item=definition: self.editor.open_edit(item),
                            ).props("flat round dense aria-label='Edit goal'")
                            ui.button(
                                icon="archive",
                                on_click=lambda _, item=series: self._archive(item),
                            ).props("flat round dense aria-label='Archive goal'")
                        ui.button(
                            icon="content_copy",
                            on_click=lambda _, item=series: self._duplicate(item),
                        ).props("flat round dense aria-label='Duplicate as one-off goal'")
                        ui.button(
                            icon="delete",
                            on_click=lambda _, item=series, title=definition.version.title:
                                self._confirm_delete(item, title),
                        ).props("flat round dense color=negative aria-label='Delete goal'")

    async def _archive(self, series: GoalSeries) -> None:
        try:
            await self.runtime.archive_goal(series.id, series.revision)
        except ConcurrentModificationError as exc:
            ui.notify(str(exc), type="warning")
            return
        ui.notify("Goal archived", type="positive")

    async def _duplicate(self, series: GoalSeries) -> None:
        try:
            await self.runtime.duplicate_goal(series.id, self._selected_start())
        except (ValueError, ConcurrentModificationError) as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify("Goal duplicated as a one-off goal", type="positive")

    def _confirm_delete(self, series: GoalSeries, title: str) -> None:
        self.pending_delete = series
        self.delete_message.set_text(f'Delete "{title}"?')
        self.delete_dialog.open()

    async def _delete(self) -> None:
        if self.pending_delete is None:
            return
        try:
            await self.runtime.delete_goal(
                self.pending_delete.id, self.pending_delete.revision
            )
        except ConcurrentModificationError as exc:
            ui.notify(str(exc), type="warning")
            return
        self.pending_delete = None
        self.delete_dialog.close()
        ui.notify("Goal deleted", type="positive")
