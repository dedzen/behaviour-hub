from nicegui import ui
from pathlib import Path

from timeline.storage.repository import SQLiteRepository
from timeline.api.timeline import Timeline

from nice_ui.pages.filter_panel import FilterPanel
from nice_ui.pages.statistics import StatisticsView
from nice_ui.pages.analytics import AnalyticsView
from nice_ui.pages.plots import PlotsView
from nice_ui.pages.events import EventsView

repo = SQLiteRepository(Path("timeline.db"))
timeline = Timeline(repo)

current_timeline = timeline
statistics: StatisticsView | None = None
analytics: AnalyticsView | None = None
plots: PlotsView | None = None
events: EventsView | None = None

def refresh():
    global current_timeline
    current_timeline = filters.timeline()
    update_statistics()
    update_analytics()
    update_plots()
    update_events()


def update_current_tab():
    # print(vars(tabs.value))
    current_tab = tabs.value
    if isinstance(current_tab, ui.tab):
        current_tab = current_tab.label 
    match current_tab:  #type: ignore
        case "Statistics": #type: ignore
            update_statistics()
        case "Analytics": #type: ignore
            update_analytics()
        case "Plots": #type: ignore
            update_plots()
        case "Event Viewer":
            update_events()

def update_statistics():
    global current_timeline
    if statistics is not None:
        statistics.update(current_timeline)
def update_analytics():
    global current_timeline
    if analytics is not None:
        analytics.update(current_timeline)
def update_plots():
    global current_timeline
    if plots is not None:
        plots.update(current_timeline)
def update_events():
    global current_timeline
    if events is not None:
        events.update(current_timeline)




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
                statistics = StatisticsView()
            with ui.tab_panel(analytics_tab):
                analytics = AnalyticsView()

            # ---------------- Plots ----------------

            with ui.tab_panel(plots_tab):
                plots = PlotsView()

            # ---------------- Events ----------------

            with ui.tab_panel(events_tab):
                events = EventsView()

        
        refresh()


ui.run()
