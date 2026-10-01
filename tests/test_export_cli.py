from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from typer.testing import CliRunner

from timeline.cli import app
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Chunk, Event
from timeline.storage.repository import SQLiteRepository


class ExportCliTest(unittest.TestCase):
    def test_export_markdown_prints_daily_note(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "timeline.db"
            with SQLiteRepository(db) as repo:
                repo.ensure_schema()
                self._insert_chunk(
                    repo,
                    datetime(2026, 8, 1, 9, 0),
                    datetime(2026, 8, 1, 10, 0),
                    DeviceSource.EMBED,
                    "Work",
                    "Working",
                )

            result = CliRunner().invoke(
                app,
                [
                    "export",
                    "markdown",
                    "2026-08-01",
                    "--database",
                    str(db),
                    "--activity",
                    "Working",
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("date: 2026-08-01", result.output)
            self.assertIn("- Working(1) - 1h | +100.0% | +100.0%", result.output)

    def test_export_markdown_writes_output_file_with_default_activities(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "timeline.db"
            output = Path(directory) / "daily.md"
            with SQLiteRepository(db) as repo:
                repo.ensure_schema()
                self._insert_chunk(
                    repo,
                    datetime(2026, 8, 1, 9, 0),
                    datetime(2026, 8, 1, 11, 0),
                    DeviceSource.EMBED,
                    "Work",
                    "Working",
                )

            result = CliRunner().invoke(
                app,
                [
                    "export",
                    "markdown",
                    "2026-08-01",
                    "--database",
                    str(db),
                    "--output",
                    str(output),
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Wrote", result.output)
            self.assertIn("- Working(1) - 2h | +100.0% | +100.0%", output.read_text())

    def test_top_activity_exclusion_does_not_filter_default_important_activities(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "timeline.db"
            with SQLiteRepository(db) as repo:
                repo.ensure_schema()
                self._insert_chunk(
                    repo,
                    datetime(2026, 8, 1, 0, 0),
                    datetime(2026, 8, 1, 8, 0),
                    DeviceSource.EMBED,
                    "Body",
                    "Sleep",
                )
                self._insert_chunk(
                    repo,
                    datetime(2026, 8, 1, 9, 0),
                    datetime(2026, 8, 1, 11, 0),
                    DeviceSource.EMBED,
                    "Work",
                    "Working",
                )

            result = CliRunner().invoke(
                app,
                [
                    "export",
                    "markdown",
                    "2026-08-01",
                    "--database",
                    str(db),
                    "--default-activities",
                    "1",
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("- Top activity: Working (2h)", result.output)
            self.assertIn("- Sleep(1) - 8h | +100.0% | +100.0%", result.output)

    def _insert_chunk(
        self,
        repo: SQLiteRepository,
        start: datetime,
        end: datetime,
        source: DeviceSource,
        category: str,
        name: str,
    ) -> None:
        start_event = Event(
            timestamp=start,
            device_source=source,
            event_kind=EventKind.INTERVAL_START,
            category=category,
            name=name,
        )
        end_event = Event(
            timestamp=end,
            device_source=source,
            event_kind=EventKind.INTERVAL_END,
            category=category,
            name=name,
        )
        repo.insert_event(start_event)
        repo.insert_event(end_event)
        repo._insert_chunk(
            Chunk(
                start_timestamp=start,
                end_timestamp=end,
                duration_seconds=int((end - start).total_seconds()),
                category=category,
                name=name,
                source=source,
                start_event_id=start_event.id, # type: ignore[arg-type]
                end_event_id=end_event.id, # type: ignore[arg-type]
            )
        )
        repo.commit()


if __name__ == "__main__":
    unittest.main()
