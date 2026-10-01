from __future__ import annotations

import inspect

from nicegui import ui

from timeline.application.mutations import ImportPreview, ImportSummary, MutationResult
from timeline.statistics.tools import human_duration


class ImportSourceCard:
    """Session-local download, preview, import, and remote-clear workflow."""

    def __init__(
        self,
        title: str,
        default_address: str,
        *,
        download,
        preview,
        import_data,
        clear_remote,
    ):
        self.download_action = download
        self.preview_action = preview
        self.import_action = import_data
        self.clear_action = clear_remote
        self.busy = False
        self.import_succeeded = False
        self.imported_address: str | None = None

        with ui.card().classes("bh-card w-full"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(title).classes("text-subtitle1 font-medium")
                self.stage = ui.badge("Ready").props("outline color=grey")
            self.address = ui.input(
                "Device address", value=default_address, on_change=self._address_changed,
            ).classes("w-full")
            with ui.row().classes("w-full gap-2 flex-wrap"):
                self.download_button = ui.button(
                    "Download & preview", icon="download", on_click=self._download_and_preview,
                )
                self.import_button = ui.button(
                    "Import", icon="upload_file", on_click=self._import,
                ).props("outline disable")
                self.clear_button = ui.button(
                    "Clear remote", icon="delete", on_click=self._open_clear_confirmation,
                ).props("outline color=negative disable")
            self.status = ui.label(
                "Download the device log to inspect it before importing."
            ).classes("text-caption text-grey-7")
            with ui.column().classes("w-full gap-2") as self.preview_panel:
                ui.separator()
                ui.label("Import preview").classes("text-subtitle2")
                self.preview_content = ui.column().classes("w-full gap-1")
            self.preview_panel.set_visibility(False)

        with ui.dialog() as self.clear_dialog, ui.card().classes(
            "bh-dialog-panel w-[30rem] max-w-full"
        ):
            ui.label("Clear remote log?").classes("text-h6")
            self.clear_message = ui.label().classes("text-body2")
            ui.label(
                "The imported local data will remain, but the device copy cannot be restored here."
            ).classes("text-caption text-grey-7")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=self.clear_dialog.close).props("flat")
                self.confirm_clear_button = ui.button(
                    "Clear remote log", icon="delete_forever", on_click=self._clear,
                ).props("color=negative")

    async def _invoke(self, action, *args):
        value = action(*args)
        return await value if inspect.isawaitable(value) else value

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for button in (self.download_button, self.import_button, self.clear_button):
            button.props("disable" if busy else "")
            if not busy:
                button.props(remove="disable")
        if not busy:
            if not self.preview_panel.visible:
                self.import_button.props("disable")
            if not self.import_succeeded:
                self.clear_button.props("disable")

    async def _download_and_preview(self) -> None:
        if self.busy:
            return
        address = (self.address.value or "").strip()
        self.import_succeeded = False
        self.preview_panel.set_visibility(False)
        self._set_busy(True)
        self.stage.set_text("Downloading")
        self.status.set_text("Downloading and parsing the device log…")
        try:
            download_message = await self._invoke(self.download_action, address)
            result: ImportPreview = await self._invoke(self.preview_action)
        except Exception as exc:
            self.stage.set_text("Failed")
            self.status.set_text(str(exc))
            ui.notify(str(exc), type="negative")
        else:
            self.import_succeeded = False
            self.stage.set_text("Previewed")
            self.status.set_text(str(download_message))
            self._render_preview(result)
        finally:
            self._set_busy(False)

    def _render_preview(self, result: ImportPreview) -> None:
        self.preview_panel.set_visibility(True)
        self.preview_content.clear()
        summary = result.summary
        with self.preview_content:
            self._summary_rows(summary)
            if result.warnings:
                ui.label(f"{len(result.warnings)} interval warnings expected").classes(
                    "text-warning text-caption"
                )

    @staticmethod
    def _row(label: str, value: str) -> None:
        with ui.row().classes("w-full justify-between gap-3"):
            ui.label(label).classes("text-caption text-grey-7")
            ui.label(value).classes("text-body2 text-right")

    def _summary_rows(self, summary: ImportSummary) -> None:
        self._row("Source", summary.source)
        if summary.first_timestamp is not None and summary.last_timestamp is not None:
            self._row(
                "Range",
                f"{summary.first_timestamp:%Y-%m-%d %H:%M} – "
                f"{summary.last_timestamp:%Y-%m-%d %H:%M}",
            )
        self._row("Parsed events", str(summary.total_events))
        self._row("New events", str(summary.new_events))
        self._row("Duplicates", str(summary.duplicate_events))
        optional = (
            ("Ignored", summary.ignored_events),
            ("Dropped orphan starts", summary.dropped_orphan_starts),
            ("Dropped short intervals", summary.dropped_short_chunks),
            ("Transition anomalies", summary.anomaly_count),
        )
        for label, value in optional:
            if value:
                self._row(label, str(value))
        if summary.unknown_time_seconds:
            self._row("Unknown state", human_duration(summary.unknown_time_seconds))

    async def _import(self) -> None:
        if self.busy or not self.preview_panel.visible:
            return
        self._set_busy(True)
        self.stage.set_text("Importing")
        self.status.set_text("Importing events and rebuilding chunks…")
        try:
            result: MutationResult = await self._invoke(self.import_action)
        except Exception as exc:
            self.stage.set_text("Failed")
            self.status.set_text(str(exc))
            ui.notify(str(exc), type="negative")
        else:
            self.import_succeeded = True
            self.imported_address = (self.address.value or "").strip()
            self.stage.set_text("Imported")
            self.status.set_text(result.message)
            if result.import_summary is not None:
                self._render_preview(ImportPreview(result.import_summary, result.warnings))
            ui.notify(result.message, type="warning" if result.warnings else "positive")
        finally:
            self._set_busy(False)

    def _open_clear_confirmation(self) -> None:
        if not self.import_succeeded or self.busy or not self.imported_address:
            return
        self.clear_message.set_text(
            f"Delete the source log from {self.imported_address}?"
        )
        self.clear_dialog.open()

    async def _clear(self) -> None:
        if self.busy or not self.import_succeeded:
            return
        self.clear_dialog.close()
        self._set_busy(True)
        try:
            message = await self._invoke(self.clear_action, self.imported_address)
        except Exception as exc:
            self.stage.set_text("Clear failed")
            self.status.set_text(str(exc))
            ui.notify(str(exc), type="negative")
        else:
            self.import_succeeded = False
            self.imported_address = None
            self.stage.set_text("Remote cleared")
            self.status.set_text(str(message))
            ui.notify(str(message), type="positive")
        finally:
            self._set_busy(False)

    def _address_changed(self, event) -> None:
        if self.imported_address is None or (event.value or "").strip() == self.imported_address:
            return
        self.import_succeeded = False
        self.imported_address = None
        self.clear_button.props("disable")
        self.status.set_text("Address changed; download and import again before clearing remote data.")
