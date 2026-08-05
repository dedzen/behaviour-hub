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

from nice_ui.keyboard_shortcuts import KeyboardShortcut, shortcut_script
from nice_ui.pages.filter_panel import FilterPanel
from nice_ui.pages.statistics import StatisticsView
from nice_ui.pages.analytics import AnalyticsView
from nice_ui.pages.plots import PlotsView
from nice_ui.pages.events import EventsView
from nice_ui.pages.screen_time import ScreenTimeIntersectionView
from nice_ui.pages.calendar import CalendarPage

repo = SQLiteRepository(Path("timeline.db"))
repo.ensure_schema()
timeline = Timeline(repo)
DATABASE_PATH = Path("timeline.db")
EMBED_INCOMING_PATH = Path("data/embed/incoming.csv")
ANDROID_UNLOCK_PATH = Path("data/android/unlock-events.jsonl")

current_timeline = timeline
statistics: StatisticsView | None = None
analytics: AnalyticsView | None = None
plots: PlotsView | None = None
events: EventsView | None = None
screen_time: ScreenTimeIntersectionView | None = None
filters: FilterPanel | None = None
tabs = None


def build_header(active_page: str):
    def navigate(event):
        match event.value:
            case "Main":
                ui.navigate.to("/")
            case "Calendar":
                ui.navigate.to("/calendar")
            case "Import/Export":
                ui.navigate.to("/import-export")

    with ui.header().classes("items-center justify-between px-6"):
        ui.label("Behaviour Hub").classes("text-h6")
        with ui.tabs(value=active_page).props( #type: ignore
            "dense shrink stretch indicator-color=white"
        ) as page_tabs:
            ui.tab("Main", icon="dashboard")
            ui.tab("Calendar", icon="calendar_month")
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


def download_android_log(ip: str) -> str:
    ip = ip.strip()
    if not ip:
        raise ValueError("Phone IP is required")

    ANDROID_UNLOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    url = f"http://{ip}/unlock-events.jsonl"

    try:
        with urllib.request.urlopen(url, timeout=10.0) as response:
            data = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download Android log from {ip}: {exc}") from exc

    ANDROID_UNLOCK_PATH.write_bytes(data)
    return f"Downloaded {len(data)} bytes to {ANDROID_UNLOCK_PATH}"


def clear_android_log(ip: str) -> str:
    ip = ip.strip()
    if not ip:
        raise ValueError("Phone IP is required")

    url = f"http://{ip}/unlock-events.jsonl"
    request = urllib.request.Request(url, method="DELETE")

    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to clear Android log on {ip}: {exc}") from exc

    return f"Cleared Android log on {ip}"


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
    rebuild_message = rebuild_chunks()
    if skipped:
        return (
            f"Imported {inserted} embed events and skipped {skipped} duplicates. "
            f"{rebuild_message}"
        )

    return f"Imported {inserted} embed events. {rebuild_message}"


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
    if result.dropped_short_chunks:
        parts.append(f"dropped {result.dropped_short_chunks} chunks shorter than 20s")
    if result.anomalies:
        parts.append(f"reported {len(result.anomalies)} transition anomalies")
    if result.unknown_time_seconds:
        parts.append(f"reported {result.unknown_time_seconds:.3f}s unknown state")
    if skipped:
        parts.append(f"skipped {skipped} duplicates")
    parts.append(rebuild_chunks())
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


def main_shortcut_script() -> str:
    return shortcut_script(
        "main",
        [
            KeyboardShortcut("1", ".main-tab-shortcut-1"),
            KeyboardShortcut("2", ".main-tab-shortcut-2"),
            KeyboardShortcut("3", ".main-tab-shortcut-3"),
            KeyboardShortcut("4", ".main-tab-shortcut-4"),
        ],
    )


def refresh():
    global current_timeline
    if filters is None:
        return
    current_timeline = filters.timeline()
    update_statistics()
    update_analytics()
    update_plots()
    update_screen_time()
    update_events()


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
        case "Screen Time":
            update_screen_time()

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
def update_screen_time():
    global current_timeline
    if screen_time is not None:
        screen_time.update(current_timeline)
def update_events():
    global current_timeline
    if events is not None:
        events.update(current_timeline)
@ui.page("/")
def main_page():
    global filters, statistics, analytics, plots, events, screen_time, tabs

    build_header("Main")

    with ui.row().classes("w-full items-start p-4"):

        with ui.card().classes("w-80"):
            filters = FilterPanel(timeline)
            filters.on_apply = refresh

        with ui.column().classes("flex-grow min-w-0"):
            with ui.tabs().classes("w-full") as tabs:
                statistics_tab = ui.tab("Statistics").classes("main-tab-shortcut-1")
                analytics_tab = ui.tab("Analytics").classes("main-tab-shortcut-2")
                plots_tab = ui.tab("Plots").classes("main-tab-shortcut-3")
                screen_time_tab = ui.tab("Screen Time").classes("main-tab-shortcut-4")
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

                # ---------------- Screen Time ----------------

                with ui.tab_panel(screen_time_tab):
                    screen_time = ScreenTimeIntersectionView()

        with ui.column().classes("w-12 shrink-0 items-center pt-2 opacity-60 hover:opacity-100"):
            with ui.button(
                icon="event_note",
                on_click=lambda: events_dialog.open(),
            ).props("flat round dense"):
                ui.tooltip("Event viewer")

        with ui.dialog() as events_dialog:
            with ui.column().classes("w-[56rem] max-w-[95vw] max-h-[90vh] bg-white p-4 rounded shadow-xl gap-3"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Event Viewer").classes("text-h6")
                    ui.button(
                        icon="close",
                        on_click=events_dialog.close,
                    ).props("flat round dense")
                events = EventsView(framed=False)

            refresh()
            ui.add_body_html(main_shortcut_script())


@ui.page("/calendar")
def calendar_page():
    build_header("Calendar")
    CalendarPage(timeline)


@ui.page("/import-export")
def import_export_page():
    build_header("Import/Export")

    with ui.column().classes("w-full p-6 gap-4"):
        ui.label("Import/Export").classes("text-h5")

        with ui.row().classes("w-full items-stretch gap-6"):
            with ui.column().classes("w-1/2 min-w-[22rem] gap-4"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Import").classes("text-h6")
                    with ui.button(
                        icon="build",
                        on_click=lambda: notify_action(rebuild_chunks),
                    ).props("flat round dense"):
                        ui.tooltip("Rebuild chunks")
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
                with ui.card().classes("w-full"):
                    ui.label("Phone").classes("text-subtitle1")
                    phone_ip = ui.input(
                        "IP",
                        value="192.168.3.44:8787",
                    ).classes("w-full")
                    with ui.row().classes("w-full gap-2"):
                        ui.button(
                            "Download log",
                            icon="download",
                            on_click=lambda: notify_action(
                                lambda: download_android_log(phone_ip.value or "")
                            ),
                        ).props("outline")
                        ui.button(
                            "Clear log",
                            icon="delete",
                            on_click=lambda: notify_action(
                                lambda: clear_android_log(phone_ip.value or "")
                            ),
                        ).props("outline color=negative")
                        ui.button(
                            "Import log",
                            icon="upload_file",
                            on_click=lambda: notify_action(
                                lambda: import_android_log(str(ANDROID_UNLOCK_PATH), "active_screen")
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
