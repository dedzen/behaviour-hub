from nicegui import ui
import os
from pathlib import Path
import urllib.error
import urllib.request

from timeline.domain.interval_builder import IntervalBuilder
from timeline.ingest.android import import_android_unlock_jsonl
from timeline.ingest.embed import import_embed_csv
from timeline.storage.repository import SQLiteRepository
from timeline.api.timeline import Timeline

from nice_ui.pages.filter_panel import FilterPanel
from nice_ui.pages.statistics import StatisticsView
from nice_ui.pages.analytics import AnalyticsView
from nice_ui.pages.plots import PlotsView
from nice_ui.pages.events import EventsView
from nice_ui.pages.day_timeline import DayTimelineView

repo = SQLiteRepository(Path("timeline.db"))
timeline = Timeline(repo)
DATABASE_PATH = Path("timeline.db")
EMBED_INCOMING_PATH = Path("data/embed/incoming.csv")
ANDROID_UNLOCK_PATH = Path("data/android/unlock-events.jsonl")

current_timeline = timeline
statistics: StatisticsView | None = None
analytics: AnalyticsView | None = None
plots: PlotsView | None = None
events: EventsView | None = None
day_timeline: DayTimelineView | None = None
filters: FilterPanel | None = None
tabs = None


def build_header(active_page: str):
    def navigate(event):
        match event.value:
            case "Main":
                ui.navigate.to("/")
            case "Import/Export":
                ui.navigate.to("/import-export")

    with ui.header().classes("items-center justify-between px-6"):
        ui.label("Behaviour Hub").classes("text-h6")
        with ui.tabs(value=active_page).props( #type: ignore
            "dense shrink stretch indicator-color=white"
        ) as page_tabs:
            ui.tab("Main", icon="dashboard")
            ui.tab("Import/Export", icon="sync_alt")
            page_tabs.on_value_change(navigate)


def placeholder_action(action: str):
    ui.notify(f"{action} is not wired yet", type="info")


def notify_action(action):
    try:
        message = action()
    except Exception as exc:
        ui.notify(str(exc), type="negative")
        return

    ui.notify(message, type="positive")


def download_embed_log(ip: str) -> str:
    ip = ip.strip()
    if not ip:
        raise ValueError("Embed IP is required")

    EMBED_INCOMING_PATH.parent.mkdir(parents=True, exist_ok=True)
    url = f"http://{ip}/log.csv"

    try:
        with urllib.request.urlopen(url, timeout=10.0) as response:
            data = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download log from {ip}: {exc}") from exc

    EMBED_INCOMING_PATH.write_bytes(data)
    return f"Downloaded {len(data)} bytes to {EMBED_INCOMING_PATH}"


def clear_embed_log(ip: str) -> str:
    ip = ip.strip()
    if not ip:
        raise ValueError("Embed IP is required")

    url = f"http://{ip}/log.csv"
    request = urllib.request.Request(url, method="DELETE")

    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to clear log on {ip}: {exc}") from exc

    return f"Cleared log on {ip}"


def import_embed_log() -> str:
    if not EMBED_INCOMING_PATH.exists():
        raise FileNotFoundError(f"No downloaded log at {EMBED_INCOMING_PATH}")

    with SQLiteRepository(DATABASE_PATH) as import_repo:
        import_repo.ensure_schema()
        events = import_embed_csv(EMBED_INCOMING_PATH)
        inserted = 0
        for event in events:
            inserted += int(import_repo.insert_event(event))

    skipped = len(events) - inserted
    if skipped:
        return f"Imported {inserted} embed events and skipped {skipped} duplicates"

    return f"Imported {inserted} embed events"


def import_android_log(filename: str, strategy: str) -> str:
    path = Path(filename.strip())
    if not path.exists():
        raise FileNotFoundError(f"No Android log at {path}")

    with SQLiteRepository(DATABASE_PATH) as import_repo:
        import_repo.ensure_schema()
        result = import_android_unlock_jsonl(path, strategy=strategy) # type: ignore[arg-type]
        inserted = 0
        for event in result.events:
            inserted += int(import_repo.insert_event(event))

    skipped = len(result.events) - inserted
    parts = [f"Imported {inserted} android events using {result.strategy} strategy"]
    if result.ignored_events:
        parts.append(f"ignored {result.ignored_events} unrelated events")
    if result.dropped_orphan_starts:
        parts.append(f"dropped {result.dropped_orphan_starts} orphan starts")
    if skipped:
        parts.append(f"skipped {skipped} duplicates")
    return ", ".join(parts)


def rebuild_chunks() -> str:
    with SQLiteRepository(DATABASE_PATH) as rebuild_repo:
        rebuild_repo.ensure_schema()
        events = rebuild_repo.load_events()
        chunks, warnings = IntervalBuilder.build(events)
        rebuild_repo.replace_chunks(chunks)

    if warnings:
        return f"Generated {len(chunks)} chunks with {len(warnings)} warnings"

    return f"Generated {len(chunks)} chunks"


def import_section(title: str, actions: list[tuple[str, str]]):
    with ui.card().classes("w-full"):
        ui.label(title).classes("text-subtitle1")
        with ui.row().classes("w-full gap-2"):
            for label, icon in actions:
                ui.button(
                    label,
                    icon=icon,
                    on_click=lambda action=label: placeholder_action(action),  #type: ignore
                ).props("outline")


def refresh():
    global current_timeline
    if filters is None:
        return
    current_timeline = filters.timeline()
    update_statistics()
    update_analytics()
    update_plots()
    update_events()
    update_day_timeline()


def update_current_tab():
    if tabs is None:
        return
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
        case "Day":
            update_day_timeline()

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
def update_day_timeline():
    global current_timeline
    if day_timeline is not None:
        day_timeline.update(current_timeline)




@ui.page("/")
def main_page():
    global filters, statistics, analytics, plots, events, day_timeline, tabs

    build_header("Main")

    with ui.row().classes("w-full items-start p-4"):

        with ui.card().classes("w-80"):
            filters = FilterPanel(timeline)
            filters.on_apply = refresh

        with ui.column().classes("flex-grow"):
            with ui.tabs().classes("w-full") as tabs:
                statistics_tab = ui.tab("Statistics")
                analytics_tab = ui.tab("Analytics")
                plots_tab = ui.tab("Plots")
                day_tab = ui.tab("Day")
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

                # ---------------- Day ----------------

                with ui.tab_panel(day_tab):
                    day_timeline = DayTimelineView()

                # ---------------- Events ----------------

                with ui.tab_panel(events_tab):
                    events = EventsView()

            
            refresh()


@ui.page("/import-export")
def import_export_page():
    build_header("Import/Export")

    with ui.column().classes("w-full p-6 gap-4"):
        ui.label("Import/Export").classes("text-h5")

        with ui.row().classes("w-full items-stretch gap-6"):
            with ui.column().classes("w-1/2 min-w-[22rem] gap-4"):
                ui.label("Import").classes("text-h6")
                with ui.card().classes("w-full"):
                    ui.label("Embed").classes("text-subtitle1")
                    embed_ip = ui.input(
                        "IP",
                        value="192.168.3.55",
                    ).classes("w-full")
                    with ui.row().classes("w-full gap-2"):
                        ui.button(
                            "Download log",
                            icon="download",
                            on_click=lambda: notify_action(
                                lambda: download_embed_log(embed_ip.value or "")
                            ),
                        ).props("outline")
                        ui.button(
                            "Clear log",
                            icon="delete",
                            on_click=lambda: notify_action(
                                lambda: clear_embed_log(embed_ip.value or "")
                            ),
                        ).props("outline color=negative")
                        ui.button(
                            "Import log",
                            icon="upload_file",
                            on_click=lambda: notify_action(import_embed_log),
                        ).props("outline")
                        ui.button(
                            "Rebuild chunks",
                            icon="build",
                            on_click=lambda: notify_action(rebuild_chunks),
                        ).props("outline")
                with ui.card().classes("w-full"):
                    ui.label("Phone").classes("text-subtitle1")
                    android_path = ui.input(
                        "JSONL path",
                        value=str(ANDROID_UNLOCK_PATH),
                    ).classes("w-full")
                    with ui.row().classes("w-full gap-2"):
                        ui.button(
                            "Import unlock events",
                            icon="lock_open",
                            on_click=lambda: notify_action(
                                lambda: import_android_log(android_path.value or "", "keyguard")
                            ),
                        ).props("outline")
                        ui.button(
                            "Import screen events",
                            icon="phone_android",
                            on_click=lambda: notify_action(
                                lambda: import_android_log(android_path.value or "", "screen")
                            ),
                        ).props("outline")
                import_section(
                    "Obsidian",
                    [
                        ("Select vault", "folder_open"),
                        ("Import notes", "article"),
                    ],
                )

            ui.separator().props("vertical").classes("self-stretch")

            with ui.column().classes("flex-1 min-w-[22rem] gap-4"):
                ui.label("Export").classes("text-h6")
                with ui.card().classes("w-full"):
                    ui.label("Export").classes("text-subtitle1")
                    with ui.row().classes("w-full gap-2"):
                        ui.button(
                            "Export data",
                            icon="ios_share",
                            on_click=lambda: placeholder_action("Export data"),
                        ).props("outline")
                        ui.button(
                            "Export report",
                            icon="description",
                            on_click=lambda: placeholder_action("Export report"),
                        ).props("outline")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=int(os.environ.get("NICEGUI_PORT", "8080")))
