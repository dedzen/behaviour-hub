from nicegui import app, ui
import inspect
import os
from pathlib import Path
import urllib.error
import urllib.request

from nice_ui.keyboard_shortcuts import KeyboardShortcut, shortcut_script
from nice_ui.pages.filter_panel import FilterPanel, previous_date_range
from nice_ui.pages.overview import OverviewView
from nice_ui.pages.statistics import StatisticsView
from nice_ui.pages.analytics import AnalyticsView
from nice_ui.pages.plots import PlotsView
from nice_ui.pages.events import EventsView
from nice_ui.pages.screen_time import ScreenTimeIntersectionView
from nice_ui.pages.calendar import CalendarPage
from nice_ui.pages.import_flow import ImportSourceCard
from nice_ui.pages.goals import GoalsPage
from nice_ui.runtime import DashboardRuntime, DashboardSession, DataChange
from nice_ui.responsive import AppShell, VIEWPORT

DATABASE_PATH = Path("timeline.db")
GOALS_DATABASE_PATH = Path(os.environ.get("GOALS_DATABASE_PATH", "goals.db"))
EMBED_INCOMING_PATH = Path("data/embed/incoming.csv")
ANDROID_UNLOCK_PATH = Path("data/android/unlock-events.jsonl")
RUNTIME = DashboardRuntime(DATABASE_PATH, GOALS_DATABASE_PATH)
app.on_startup(RUNTIME.initialize)


def build_header(active_page: str, *, on_filter=None) -> AppShell:
    return AppShell(active_page, on_filter=on_filter)


async def notify_action(action):
    try:
        message = action()
        if inspect.isawaitable(message):
            message = await message
    except Exception as exc:
        ui.notify(str(exc), type="negative")
        return

    if message is not None:
        ui.notify(str(getattr(message, "message", message)), type="positive")


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


def main_shortcut_script() -> str:
    return shortcut_script(
        "main",
        [
            KeyboardShortcut("1", ".main-tab-shortcut-1"),
            KeyboardShortcut("2", ".main-tab-shortcut-2"),
            KeyboardShortcut("3", ".main-tab-shortcut-3"),
            KeyboardShortcut("4", ".main-tab-shortcut-4"),
            KeyboardShortcut("5", ".main-tab-shortcut-5"),
        ],
    )


class MainDashboard:
    def __init__(self, session: DashboardSession):
        self.session = session
        self.current_timeline = session.timeline
        self._dirty_tabs: set[str] = set()

        with ui.left_drawer(value=None, bordered=True).props("width=320 breakpoint=1024").classes(
            "bh-filter-drawer bg-white"
        ) as self.filter_drawer:
            self.filters = FilterPanel(session.timeline, on_apply=self._apply_filters)

        build_header("Main", on_filter=self.filter_drawer.toggle)
        with ui.column().classes("bh-page w-full p-4 gap-3"):
            with ui.row().classes(
                "bh-filter-summary bh-mobile-only w-full items-center gap-2 no-wrap overflow-x-auto"
            ) as self.filter_summary:
                pass

            with ui.column().classes(
                "bh-dashboard-content w-full max-w-none flex-grow min-w-0 self-stretch"
            ) as self.dashboard_content:
                with ui.tabs().props("dense no-caps align=left mobile-arrows outside-arrows").classes(
                    "bh-dashboard-tabs w-full overflow-x-auto"
                ) as self.tabs:
                    overview_tab = ui.tab("Overview", icon="space_dashboard").classes(
                        "main-tab-shortcut-1"
                    )
                    statistics_tab = ui.tab("Statistics", icon="query_stats").classes(
                        "main-tab-shortcut-2"
                    )
                    analytics_tab = ui.tab("Analytics", icon="table_chart").classes(
                        "main-tab-shortcut-3"
                    )
                    plots_tab = ui.tab("Plots", icon="insert_chart").classes(
                        "main-tab-shortcut-4"
                    )
                    screen_time_tab = ui.tab("Screen Time", icon="phone_android").classes(
                        "main-tab-shortcut-5"
                    )
                with ui.tab_panels(self.tabs, value=overview_tab).classes(
                    "bh-tab-panels w-full bg-transparent"
                ):
                    with ui.tab_panel(overview_tab):
                        self.overview = OverviewView()
                    with ui.tab_panel(statistics_tab):
                        self.statistics = StatisticsView()
                    with ui.tab_panel(analytics_tab):
                        self.analytics = AnalyticsView()
                    with ui.tab_panel(plots_tab):
                        self.plots = PlotsView()
                    with ui.tab_panel(screen_time_tab):
                        self.screen_time = ScreenTimeIntersectionView()
                self.tabs.on_value_change(lambda _: self.update_current_tab())

            with ui.column().classes(
                "fixed right-3 bottom-20 lg:bottom-4 z-20 items-center opacity-80 hover:opacity-100"
            ):
                with ui.button(
                    icon="event_note",
                    on_click=lambda: events_dialog.open(),
                ).props("round color=primary aria-label='Open event viewer'"):
                    ui.tooltip("Event viewer")

            with ui.dialog() as events_dialog:
                with ui.column().classes(
                    "bh-dialog-panel w-[56rem] max-w-[95vw] max-h-[90vh] "
                    "bg-white p-4 rounded shadow-xl gap-3"
                ):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Event Viewer").classes("text-h6")
                        ui.button(icon="close", on_click=events_dialog.close).props(
                            "flat round dense"
                        )
                    self.events = EventsView(
                        framed=False,
                        mutation_api=session.runtime,
                    )

        self.refresh()
        ui.add_body_html(main_shortcut_script())

    async def _apply_filters(self) -> None:
        self.refresh()
        is_mobile = await ui.run_javascript("window.innerWidth < 1024")
        if is_mobile:
            self.filter_drawer.hide()

    def _render_filter_summary(self) -> None:
        self.filter_summary.clear()
        with self.filter_summary:
            ui.button(icon="tune", on_click=self.filter_drawer.toggle).props(
                "flat round dense aria-label=Filters"
            )
            for kind, label in self.filters.summary_items():
                ui.chip(
                    label,
                    removable=True,
                    on_value_change=lambda event, selected=kind: (
                        self.filters.remove_summary(selected) if not event.value else None
                    ),
                ).props("outline color=primary dense").classes("whitespace-nowrap")

    def refresh(self) -> None:
        self.current_timeline = self.filters.timeline()
        self.events.update(self.current_timeline)
        self._render_filter_summary()
        self._dirty_tabs = {"Overview", "Statistics", "Analytics", "Plots", "Screen Time"}
        self.update_current_tab()

    def update_current_tab(self) -> None:
        current_tab = self.tabs.value
        if isinstance(current_tab, ui.tab):
            current_tab = current_tab.label
        if current_tab not in self._dirty_tabs:
            return
        match current_tab:
            case "Overview":
                start, end = previous_date_range(
                    self.current_timeline.query.start,
                    self.current_timeline.query.end,
                )
                previous = (
                    self.current_timeline.between(start, end)
                    if start is not None and end is not None
                    else None
                )
                self.overview.update(
                    self.current_timeline,
                    previous,
                    range_label=self.filters.range_label(),
                )
            case "Statistics":
                self.statistics.update(self.current_timeline)
            case "Analytics":
                self.analytics.update(self.current_timeline)
            case "Plots":
                self.plots.update(self.current_timeline)
            case "Screen Time":
                self.screen_time.update(self.current_timeline)
        self._dirty_tabs.discard(current_tab)

    def database_changed(self, change: DataChange) -> None:
        if not change.events_changed:
            return
        self.filters.refresh_options()
        self.current_timeline = self.filters.timeline()
        self.events.database_changed(self.current_timeline)
        self._render_filter_summary()
        self._dirty_tabs = {"Overview", "Statistics", "Analytics", "Plots", "Screen Time"}
        self.update_current_tab()


@ui.page("/", viewport=VIEWPORT)
def main_page():
    session = DashboardSession(RUNTIME, ui.context.client)
    dashboard = MainDashboard(session)
    session.subscribe(dashboard.database_changed)


@ui.page("/calendar", viewport=VIEWPORT)
def calendar_page():
    build_header("Calendar")
    session = DashboardSession(RUNTIME, ui.context.client)
    calendar = CalendarPage(
        session.timeline,
        goal_repo=session.goal_repo,
        mutation_api=session.runtime,
    )
    session.subscribe(
        lambda change: calendar.database_changed(
            events_changed=change.events_changed,
            marker_days=change.marker_days,
            goals_changed=change.goals_changed,
        )
    )


@ui.page("/goals", viewport=VIEWPORT)
def goals_page():
    build_header("Goals")
    session = DashboardSession(RUNTIME, ui.context.client)
    goals = GoalsPage(session.timeline, session.goal_repo, session.runtime)
    session.subscribe(goals.database_changed)


@ui.page("/import-export", viewport=VIEWPORT)
def import_export_page():
    build_header("Import/Export")

    with ui.column().classes("bh-page w-full p-6 gap-4"):
        ui.label("Import/Export").classes("text-h5")

        with ui.row().classes("w-full items-stretch gap-6 flex-col lg:flex-row"):
            with ui.column().classes("w-full lg:w-1/2 min-w-0 gap-4"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Import").classes("text-h6")
                    with ui.button(
                        icon="build",
                        on_click=lambda: notify_action(RUNTIME.rebuild_chunks),
                    ).props("flat round dense"):
                        ui.tooltip("Rebuild chunks")
                ImportSourceCard(
                    "Embed",
                    "192.168.3.55",
                    download=lambda address: RUNTIME.run_io(
                        lambda: download_embed_log(address)
                    ),
                    preview=lambda: RUNTIME.preview_embed(EMBED_INCOMING_PATH),
                    import_data=lambda: RUNTIME.import_embed(EMBED_INCOMING_PATH),
                    clear_remote=lambda address: RUNTIME.run_io(
                        lambda: clear_embed_log(address)
                    ),
                )
                ImportSourceCard(
                    "Phone",
                    "192.168.3.44:8787",
                    download=lambda address: RUNTIME.run_io(
                        lambda: download_android_log(address)
                    ),
                    preview=lambda: RUNTIME.preview_android(
                        ANDROID_UNLOCK_PATH, "active_screen"
                    ),
                    import_data=lambda: RUNTIME.import_android(
                        ANDROID_UNLOCK_PATH, "active_screen"
                    ),
                    clear_remote=lambda address: RUNTIME.run_io(
                        lambda: clear_android_log(address)
                    ),
                )
                with ui.card().classes("bh-card w-full opacity-70"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Obsidian").classes("text-subtitle1")
                        ui.badge("Coming later").props("outline color=grey")
                    ui.label("Vault note import is not available in this release.").classes(
                        "text-caption text-grey-7"
                    )

            ui.separator().props("vertical").classes("self-stretch bh-desktop-only")

            with ui.column().classes("flex-1 min-w-0 gap-4"):
                ui.label("Export").classes("text-h6")
                with ui.card().classes("w-full"):
                    ui.label("Export").classes("text-subtitle1")
                    ui.label(
                        "Dashboard exports are coming later. Daily Markdown export remains available in the CLI."
                    ).classes("text-body2 text-grey-7")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=int(os.environ.get("NICEGUI_PORT", "8080")))
