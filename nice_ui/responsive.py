from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nicegui import ui


VIEWPORT = "width=device-width, initial-scale=1, viewport-fit=cover"


@dataclass(frozen=True, slots=True)
class NavigationItem:
    key: str
    label: str
    icon: str
    path: str


NAVIGATION = (
    NavigationItem("Main", "Dashboard", "dashboard", "/"),
    NavigationItem("Calendar", "Calendar", "calendar_month", "/calendar"),
    NavigationItem("Import/Export", "Transfer", "sync_alt", "/import-export"),
)


RESPONSIVE_CSS = r"""
:root {
  --bh-mobile-nav-height: 58px;
  --bh-page-gap: 1rem;
}

html, body {
  min-width: 320px;
}

.bh-header {
  padding-left: max(1rem, env(safe-area-inset-left));
  padding-right: max(1rem, env(safe-area-inset-right));
}

.bh-mobile-nav {
  padding-right: env(safe-area-inset-right);
  padding-bottom: env(safe-area-inset-bottom);
  padding-left: env(safe-area-inset-left);
}

.bh-mobile-nav .q-tab {
  min-height: var(--bh-mobile-nav-height);
  min-width: 0;
  padding: 4px 6px;
}

.bh-mobile-nav .q-tab__label {
  font-size: 11px;
  line-height: 1.1;
}

.bh-responsive-table {
  overflow-x: auto;
}

.bh-responsive-table .q-table th,
.bh-responsive-table .q-table td {
  white-space: nowrap;
}

.bh-filter-drawer {
  padding: 1rem;
}

.bh-filter-summary {
  scrollbar-width: none;
}

.bh-filter-summary::-webkit-scrollbar {
  display: none;
}

.bh-dashboard-content,
.bh-dashboard-content > .q-tabs,
.bh-dashboard-content > .q-tab-panels {
  width: 100%;
  max-width: none;
}

@media (max-width: 1023px) {
  :root {
    --bh-page-gap: .65rem;
  }

  .bh-desktop-only {
    display: none !important;
  }

  .nicegui-content {
    padding-bottom: calc(var(--bh-mobile-nav-height) + env(safe-area-inset-bottom));
  }

  .bh-header {
    min-height: 52px;
    padding-top: env(safe-area-inset-top);
  }

  .bh-page {
    padding: .65rem !important;
    gap: .65rem !important;
  }

  .bh-card {
    padding: .75rem !important;
    border-radius: .65rem !important;
  }

  .bh-dashboard-tabs .q-tab {
    min-width: 78px;
    padding: 0 8px;
  }

  .bh-dashboard-tabs .q-tab__label {
    font-size: 12px;
  }

  .bh-tab-panels .q-tab-panel {
    padding: .5rem 0 0 0;
  }

  .bh-responsive-table .q-table th,
  .bh-responsive-table .q-table td {
    padding: 7px 8px;
    font-size: 12px;
  }

  .bh-dialog-panel {
    width: 100vw !important;
    max-width: 100vw !important;
    max-height: calc(100vh - env(safe-area-inset-top)) !important;
    min-height: min(100%, 32rem);
    margin: 0 !important;
    border-radius: 1rem 1rem 0 0 !important;
    padding: .85rem !important;
  }

  .q-dialog__inner:has(.bh-dialog-panel) {
    padding: 0 !important;
    align-items: flex-end !important;
  }

  .bh-chart {
    height: 18rem !important;
  }

  .bh-chart-compact {
    height: 15rem !important;
  }

  .bh-calendar-cell {
    min-height: 3.8rem !important;
    padding: .25rem !important;
    gap: 0 !important;
  }

  .bh-calendar-cell .q-label {
    line-height: 1.05;
  }
}

@media (max-width: 639px) {
  .bh-calendar-cell {
    min-height: 3.35rem !important;
  }

  .bh-calendar-secondary {
    font-size: 10px !important;
  }
}

@media (min-width: 1024px) {
  .bh-mobile-only {
    display: none !important;
  }
}
"""


def navigate_to(key: str) -> None:
    item = next((item for item in NAVIGATION if item.key == key), None)
    if item is not None:
        ui.navigate.to(item.path)


class AppShell:
    """Shared adaptive navigation with a single future metadata insertion point."""

    def __init__(self, active_page: str, *, on_filter=None):
        ui.add_css(RESPONSIVE_CSS)
        active = next(item for item in NAVIGATION if item.key == active_page)

        with ui.header().classes("bh-header items-center justify-between gap-2"):
            with ui.row().classes("items-center gap-2 min-w-0"):
                if on_filter is not None:
                    ui.button(icon="tune", on_click=on_filter).props(
                        "flat round dense aria-label=Filters"
                    ).classes("bh-mobile-only")
                ui.label("Behaviour Hub").classes("text-h6 bh-desktop-only")
                ui.label(active.label).classes("text-subtitle1 truncate bh-mobile-only")

            with ui.tabs(value=active_page).props(
                "dense shrink stretch indicator-color=white no-caps"
            ).classes("bh-desktop-only") as desktop_tabs:
                for item in NAVIGATION:
                    ui.tab(item.key, label=item.label, icon=item.icon)
                desktop_tabs.on_value_change(lambda event: navigate_to(event.value))

        with ui.footer(fixed=True, bordered=True, wrap=False).classes(
            "bh-mobile-nav bh-mobile-only bg-white text-grey-8"
        ):
            with ui.tabs(value=active_page).props(
                "dense stretch no-caps active-color=primary indicator-color=primary align=justify"
            ).classes("w-full") as mobile_tabs:
                for item in NAVIGATION:
                    ui.tab(item.key, label=item.label, icon=item.icon)
                mobile_tabs.on_value_change(lambda event: navigate_to(event.value))


def visible_columns_expression(mobile: list[str], desktop: list[str]) -> str:
    mobile_js = ",".join(f"'{name}'" for name in mobile)
    desktop_js = ",".join(f"'{name}'" for name in desktop)
    return f":visible-columns=\"$q.screen.lt.md ? [{mobile_js}] : [{desktop_js}]\""


def configure_responsive_table(
    table,
    columns: list[dict[str, Any]],
    *,
    mobile_columns: list[str],
    row_details: bool = True,
) -> None:
    desktop_columns = [column["name"] for column in columns]
    table.props("dense flat " + visible_columns_expression(mobile_columns, desktop_columns))
    table.classes("bh-responsive-table")
    if not row_details:
        return

    with ui.dialog() as dialog, ui.card().classes("bh-dialog-panel w-[30rem] max-w-full"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Details").classes("text-h6")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")
        details = ui.column().classes("w-full gap-2")

    labels = {column["name"]: column["label"] for column in columns}

    def show_details(event) -> None:
        row = event.args[1] if len(event.args) > 1 else None
        if not row:
            return
        details.clear()
        with details:
            for name in desktop_columns:
                with ui.row().classes("w-full justify-between gap-3"):
                    ui.label(labels[name]).classes("text-caption text-grey-7")
                    ui.label(str(row.get(name, ""))).classes(
                        "text-body2 text-right break-words min-w-0"
                    )
        dialog.open()

    table.on("rowClick", show_details)


def responsive_chart_options(options: dict, *, pie: bool = False) -> dict:
    if not options.get("series"):
        return options
    mobile_option: dict[str, Any] = {
        "legend": {
            "type": "scroll",
            "orient": "horizontal",
            "left": 8,
            "right": 8,
            "top": "auto",
            "bottom": 0,
        },
    }
    if pie:
        mobile_option["series"] = [{"center": ["50%", "42%"], "radius": ["30%", "62%"]}]
    else:
        mobile_option.update({
            "grid": {"left": 42, "right": 10, "top": 32, "bottom": 72},
            "xAxis": {"axisLabel": {"fontSize": 10, "rotate": 35, "hideOverlap": True}},
            "yAxis": {"name": "", "axisLabel": {"fontSize": 10}},
        })
    options["media"] = [{"query": {"maxWidth": 600}, "option": mobile_option}]
    return options
