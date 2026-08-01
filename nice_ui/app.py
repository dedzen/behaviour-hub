from nicegui import ui
from pathlib import Path

from timeline.storage.repository import SQLiteRepository
from timeline.api.timeline import Timeline

from nice_ui.pages.filter_panel import FilterPanel
from nice_ui.pages.summary import SummaryView
from nice_ui.pages.by_activity import ActivityView
from nice_ui.pages.by_day import DailyView

repo = SQLiteRepository(Path("timeline.db"))
timeline = Timeline(repo)

current_timeline = timeline
def refresh():
    global current_timeline
    current_timeline = filters.timeline()
    update_current_tab()


def update_current_tab():
    # print(vars(tabs.value))
    current_tab = tabs.value
    if isinstance(current_tab, ui.tab):
        current_tab = current_tab.label 
    match current_tab:  #type: ignore
        case "Statistics": #type: ignore
            update_statistics()
        case "analytics_tab": #type: ignore
            update_analytics()
        case "plots_tab": #type: ignore
            update_plots()
        case "events_tab":
            update_events()

def update_statistics():
    global current_timeline
    summary.update(current_timeline)
    if len(current_timeline.statistics.chunks.by_activity()) > 1:
        by_activity.set_visible(True)
        by_activity.update(current_timeline)
    else:
        by_activity.set_visible(False)

    if len(current_timeline.statistics.chunks.by_day()) > 1:
        by_day.set_visible(True)
        by_day.update(current_timeline)
    else:
        by_day.set_visible(False)
def update_analytics():
    pass
def update_plots():
    pass
def update_events():
    pass




with ui.row().classes("w-full items-start"):

    with ui.card().classes("w-80"):
        filters = FilterPanel(timeline)
        filters.on_apply = refresh

    with ui.column().classes("flex-grow"):
        with ui.tabs().classes("w-full") as tabs:
            statistics_tab = ui.tab("Statistics")
            analytics_tab = ui.tab("Analytics")
            plots_tab = ui.tab("Plots")
            events_tab = ui.tab("Event Viewer")
            tabs.on_value_change(lambda _: update_current_tab())
        with ui.tab_panels(tabs, value=analytics_tab).classes("w-full"):

            # ---------------- Statistics ----------------

            with ui.tab_panel(statistics_tab):

                summary = SummaryView()
                by_activity = ActivityView()
                by_day = DailyView()
            with ui.tab_panel(analytics_tab):

                with ui.card().classes("w-full"):
                    ui.label("Analytics")
                    ui.label("Coming soon...")

            # ---------------- Plots ----------------

            with ui.tab_panel(plots_tab):

                with ui.card().classes("w-full"):
                    ui.label("Plots")
                    ui.label("Coming soon...")

            # ---------------- Events ----------------

            with ui.tab_panel(events_tab):

                with ui.card().classes("w-full"):
                    ui.label("Event Viewer")
                    ui.label("Coming soon...")

        
        refresh()


ui.run()