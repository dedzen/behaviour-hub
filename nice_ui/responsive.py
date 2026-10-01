from __future__ import annotations

from dataclasses import dataclass
from html import escape
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
    NavigationItem("Goals", "Goals", "flag", "/goals"),
    NavigationItem("Import/Export", "Transfer", "sync_alt", "/import-export"),
)


RESPONSIVE_CSS = r"""
:root {
  --bh-mobile-nav-height: 58px;
  --bh-page-gap: 1rem;
  --bh-surface: #ffffff;
  --bh-surface-subtle: #f8fafc;
  --bh-border: #e2e8f0;
  --bh-text-muted: #64748b;
  --bh-radius: .8rem;
  --bh-shadow: 0 1px 2px rgba(15, 23, 42, .05);
}

html, body {
  min-width: 320px;
  background: var(--bh-surface-subtle);
}

.bh-card {
  border: 1px solid var(--bh-border);
  border-radius: var(--bh-radius);
  box-shadow: var(--bh-shadow);
}

.bh-kpi-card {
  min-height: 8.5rem;
  justify-content: space-between;
}

.bh-kpi-value {
  font-size: clamp(1.6rem, 3vw, 2.1rem);
  font-weight: 650;
  line-height: 1.1;
  letter-spacing: -.025em;
}

.bh-empty-state {
  width: 100%;
  min-height: 8rem;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  text-align: center;
  color: var(--bh-text-muted);
  border: 1px dashed var(--bh-border);
  border-radius: .65rem;
}

.q-btn:focus-visible,
.q-tab:focus-visible,
[tabindex]:focus-visible {
  outline: 3px solid rgba(37, 99, 235, .35);
  outline-offset: 2px;
}

.bh-header {
  padding-left: max(1rem, env(safe-area-inset-left));
  padding-right: max(1rem, env(safe-area-inset-right));
  z-index: 5000 !important;
  pointer-events: auto !important;
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

.bh-desktop-nav {
  display: flex;
  align-items: center;
  gap: 8px;
  position: fixed;
  top: max(8px, env(safe-area-inset-top));
  right: max(16px, env(safe-area-inset-right));
  z-index: 10000;
  pointer-events: auto !important;
}

.bh-desktop-nav-item {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 38px;
  padding: 0 14px;
  border: 1px solid rgba(255, 255, 255, .55);
  border-radius: 8px;
  color: #ffffff !important;
  background: transparent;
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
  text-decoration: none !important;
  cursor: pointer;
  pointer-events: auto !important;
  opacity: 1 !important;
  transition: background-color .12s ease, color .12s ease, border-color .12s ease;
}

.bh-desktop-nav-item:hover,
.bh-desktop-nav-item:focus-visible,
.bh-desktop-nav-item-active {
  color: #1d4ed8 !important;
  background: #ffffff;
  border-color: #ffffff;
  outline: none;
}

.bh-desktop-nav-item .material-icons {
  font-size: 19px;
}

.bh-nav-link {
  display: flex;
  text-decoration: none;
}

.bh-mobile-nav .bh-nav-link {
  min-width: 0;
  min-height: var(--bh-mobile-nav-height);
  padding: 5px 4px;
  color: #64748b;
}

.bh-mobile-nav .bh-nav-link-active {
  color: #2563eb;
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

        # Keep desktop navigation outside Quasar's header stacking context.
        # It is positioned over the header visually, but remains an independent
        # native hit target just like the working mobile navigation.
        ui.html(desktop_navigation_html(active_page), sanitize=False)

        with ui.footer(fixed=True, bordered=True, wrap=False).classes(
            "bh-mobile-nav bh-mobile-only bg-white text-grey-8"
        ):
            with ui.row().classes("w-full no-wrap items-stretch gap-0"):
                for item in NAVIGATION:
                    classes = "bh-nav-link flex-1 items-center justify-center"
                    if item.key == active_page:
                        classes += " bh-nav-link-active"
                    with ui.link(target=item.path).classes(classes):
                        with ui.column().classes("items-center justify-center gap-0"):
                            ui.icon(item.icon).classes("text-xl")
                            ui.label(item.label).classes("text-[11px] leading-tight")


def desktop_navigation_html(active_page: str) -> str:
    links = []
    for item in NAVIGATION:
        classes = "bh-desktop-nav-item"
        if item.key == active_page:
            classes += " bh-desktop-nav-item-active"
        links.append(
            f'<a class="{classes}" href="{escape(item.path, quote=True)}" '
            f'aria-current="{"page" if item.key == active_page else "false"}">'
            f'<span class="material-icons" aria-hidden="true">{escape(item.icon)}</span>'
            f'<span>{escape(item.label)}</span></a>'
        )
    return (
        '<nav class="bh-desktop-nav bh-desktop-only" aria-label="Primary navigation">'
        + "".join(links)
        + "</nav>"
    )


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
